import copy
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from alembic import command
from alembic.config import Config
from PIL import Image
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from colorstats import retention
from colorstats.analyze import color, shade
from colorstats.collect import stage
from colorstats.pack_boundary import validate_public
from colorstats.queue import Claim, RunInfo
from colorstats.schema.models import Asset, Retention, RetentionFile, RetentionStop, Source
from tests.test_collect import claim_for, payload_for
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue

ISSUE = "https://github.com/mc-blueprint/mc-blueprint-color-stats/issues/88"
DB = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="隔離PostgreSQL16専用")


@pytest.fixture
def managed(queue, asset, tmp_path):
    with queue.engine.begin() as connection:
        connection.execute(RetentionStop.__table__.delete())
    path = tmp_path / "private.jpg"
    Image.new("RGB", (8, 8), "orange").save(path)
    with Session(queue.engine) as session, session.begin():
        image = session.get(Asset, asset)
        image.storage_path = str(path)
        retention.register_asset(session, image, {}, "test")
    return asset, path


@pytest.fixture
def legacy_managed(queue, managed):
    aid, path = managed
    with Session(queue.engine) as session, session.begin():
        session.execute(RetentionFile.__table__.delete().where(RetentionFile.asset_id == aid))
        session.execute(Retention.__table__.delete().where(Retention.asset_id == aid))
    return aid, path


@DB
def test_短い期限と画像再利用停止は数値利用と独立(queue, managed):
    aid, path = managed
    with Session(queue.engine) as session, session.begin():
        record = session.scalar(select(Retention))
        record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with Session(queue.engine) as session:
        with pytest.raises(PermissionError):
            retention.assert_usable(session, aid, images=True)
        retention.assert_usable(session, aid)
    with Session(queue.engine) as session, session.begin():
        retention.cleanup(session, host="test")
    assert not path.exists()
    with Session(queue.engine) as session:
        file = session.scalar(select(RetentionFile))
        assert file.released_at and file.deleted_at and file.error is None
        retention.assert_usable(session, aid)


@DB
@pytest.mark.parametrize("reason", ["deletion_request", "rights_revoked", "rejected"])
def test_受付で再取得とstatsと処理中完了を停止する(queue, managed, reason):
    aid, _ = managed
    queue.enqueue("prep", aid, "1" * 64, {})
    claim = queue.claim(("prep",))
    with Session(queue.engine) as session, session.begin():
        retention.stop(session, source_url="https://example.test/source",
                       request_url=ISSUE, reason=reason)
    with Session(queue.engine) as session:
        with pytest.raises(PermissionError):
            retention.check_acquisition(session, "test", "https://example.test/source",
                                        "https://example.test/image")
        with pytest.raises(PermissionError):
            retention.check_selection(session, {"assets": [{"asset_id": str(aid)}]})
        record = session.scalar(select(Retention))
        assert record.request_url == ISSUE and record.stopped_at
        assert record.expires_at <= record.stopped_at + timedelta(days=7)
        assert record.backup_until <= record.stopped_at + timedelta(days=30)
    with pytest.raises(PermissionError):
        queue.complete(claim, RunInfo("open", "test", "0.1.0", "test", {}), lambda s, r: None)


@DB
def test_共有ファイルと既存画像を保護し最後の解除後に削除する(queue, managed):
    aid, path = managed
    with Session(queue.engine) as session, session.begin():
        image = session.get(Asset, aid)
        other = Asset(**{c.name: getattr(image, c.name) for c in Asset.__table__.columns
                         if c.name != "id"})
        session.add(other)
        session.flush()
        other_id = other.id
        session.scalar(select(Retention)).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with Session(queue.engine) as session, session.begin():
        retention.cleanup(session, host="test")
    assert path.exists()
    with Session(queue.engine) as session, session.begin():
        assert session.scalar(select(RetentionFile)).error == "shared_reference"
        session.get(Asset, other_id).storage_path = "preserved-elsewhere"
    with Session(queue.engine) as session, session.begin():
        retention.cleanup(session, host="test")
    assert not path.exists()


@DB
@pytest.mark.parametrize("kind", ["raw", "derived", "mask", "cvat", "replica", "cache", "backup"])
def test_全保存先の削除失敗と再開を監査する(queue, managed, monkeypatch, kind):
    aid, path = managed
    with Session(queue.engine) as session, session.begin():
        file = session.scalar(select(RetentionFile))
        file.kind = kind
        record = session.scalar(select(Retention))
        record.expires_at = record.backup_until = datetime.now(UTC) - timedelta(seconds=1)
    unlink = Path.unlink

    def failure(self, *args, **kwargs):
        if self == path:
            raise OSError("注入したI/O失敗")
        return unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failure)
    with Session(queue.engine) as session, session.begin():
        retention.cleanup(session, host="test")
        file = session.scalar(select(RetentionFile))
        assert file.released_at and file.deleted_at is None and "I/O" in file.error
    monkeypatch.setattr(Path, "unlink", unlink)
    with Session(queue.engine) as session, session.begin():
        retention.cleanup(session, host="test")
        assert session.scalar(select(RetentionFile)).deleted_at
    assert not path.exists()


@DB
def test_復元時はDBにない出典の台帳も適用し再取得を止める(queue, managed):
    with Session(queue.engine) as session, session.begin():
        retention.stop(session, source_url="https://example.test/source", request_url=ISSUE)
        entries = retention.export_tombstones(session)
    with queue.engine.begin() as connection:
        connection.execute(RetentionStop.__table__.delete())
        connection.execute(Source.__table__.update().values(policy={}))
    with Session(queue.engine) as session, session.begin():
        retention.apply_tombstones(session, entries)
        absent = copy.deepcopy(entries)
        absent[0]["source_url"] = "https://example.test/absent"
        retention.apply_tombstones(session, absent)
    with Session(queue.engine) as session:
        for url in (entries[0]["source_url"], absent[0]["source_url"]):
            with pytest.raises(PermissionError):
                retention.check_acquisition(session, "test", url, "unknown")


def test_人物maskで人物色と部位面積を除外する(tmp_path):
    image = Image.new("RGB", (4, 2), "red")
    image.paste("blue", (2, 0, 4, 2))
    source = tmp_path / "image.png"
    image.save(source)
    people = Image.new("L", image.size)
    people.paste(255, (0, 0, 2, 2))
    person = tmp_path / "person.png"
    people.save(person)
    payload = {"input_path": str(source), "person_mask": str(person),
               "output_path": str(tmp_path / "color.json"), "license_class": "open",
               "taxonomy_version": "0.1.0"}
    claim = Claim(uuid.uuid4(), uuid.uuid4(), "color", uuid.uuid4(), "a" * 64,
                  payload, 1, datetime.now(UTC))
    prepared = color.prepare(claim)
    assert len(prepared.data["observations"]) == 1
    expected = color.extract_colors(Image.new("RGB", (2, 2), "blue"))
    assert prepared.data["observations"] == expected


def test_shadeの色観測と面積にも人物を含めない(tmp_path):
    image = Image.new("RGB", (4, 2), "red")
    image.paste("blue", (2, 0, 4, 2))
    mask = tmp_path / "region.png"
    Image.new("L", image.size, 255).save(mask)
    people = np.zeros((2, 4), dtype=bool)
    people[:, :2] = True
    regions = [{"region_id": "r", "mask_path": str(mask), "label_source": "model",
                "size": [4, 2]}]
    rows = shade.observations(image, np.asarray(image) / 255, regions, person_mask=people)
    assert rows[0]["area"] == 4
    expected = color.extract_colors(Image.new("RGB", (2, 2), "blue"))[0]["observed_oklab"]
    assert rows[0]["observations"][0]["observed_oklab"]["dominant"] == expected["dominant"]


@DB
def test_新規画像は人物確認なしの色処理を拒否する(queue, managed):
    aid, _ = managed
    with Session(queue.engine) as session, session.begin():
        with pytest.raises(PermissionError):
            retention.check_privacy(session, aid, {})
        with pytest.raises(PermissionError, match="新契約"):
            retention.review_privacy(session, aid, reviewer="test", subject="person")
        with pytest.raises(PermissionError, match="新契約"):
            retention.review_privacy(session, aid, reviewer="test", subject="building")
        with pytest.raises(PermissionError, match="新契約"):
            retention.check_privacy(session, aid, {})


@DB
def test_新規画像は旧自動判定と人の上書きでは採用できない(queue, managed):
    aid, _ = managed
    with Session(queue.engine) as session, session.begin():
        with pytest.raises(PermissionError, match="新契約"):
            retention.review_privacy(session, aid, reviewer="auto:v2", subject="building",
                                     method="person-v2")
        with pytest.raises(PermissionError, match="新契約"):
            retention.review_privacy(session, aid, reviewer="auto:v2", subject="building",
                                     method="person-v2", thresholds={"mask_max": .01},
                                     evidence={"input_sha256": "a" * 64})
        with pytest.raises(PermissionError, match="新契約"):
            retention.check_privacy(session, aid, {"input_sha256": "a" * 64})
        with pytest.raises(PermissionError, match="新契約"):
            retention.review_privacy(session, aid, reviewer="human", subject="building",
                                     decision="pending")
        with pytest.raises(PermissionError, match="新契約"):
            retention.check_privacy(session, aid, {})
        assert "privacy_review" not in session.get(Asset, aid).quality


@DB
def test_旧cohortの目視取込は後日の誤り申告で承認を取り消す(queue, legacy_managed, tmp_path):
    from bench.issue114.privacy import digest, import_reviews, review_state, save

    aid, image = legacy_managed
    execution = tmp_path / "execution"
    execution.mkdir()
    save(execution / "privacy-decisions.json", [{
        "asset_id": str(aid), "decision": "accepted", "subject": "building",
        "input_path": str(image), "person_ratio": 0,
    }])
    save(execution / "review-manifest.json", {
        "required_ids": [str(aid)], "rows": [{"asset_id": str(aid)}],
    })
    with Session(queue.engine) as session, session.begin():
        retention.review_privacy(session, aid, reviewer="auto:v2", subject="building",
                                 method="person-v2", thresholds={"mask_max": .01},
                                 evidence={"input_sha256": digest(image)})
    result = {"reviewer": "目視者", "confirm_no_errors": True,
              "decisions_sha256": digest(execution / "privacy-decisions.json"), "rows": [{
                  "asset_id": str(aid), "decision": "same", "subject": "building",
                  "error_found": False, "note": "確認済み",
              }]}
    source = tmp_path / "review.json"
    source.write_text(json.dumps(result))
    import_reviews(queue.engine, execution, source)
    approval = json.loads((execution / "privacy-validation.json").read_text())
    assert approval["approved"]
    assert approval["review_state_sha256"] == review_state(queue.engine, [str(aid)])
    result["rows"][0].update(decision="pending", error_found=True)
    source.write_text(json.dumps(result))
    import_reviews(queue.engine, execution, source)
    assert not json.loads((execution / "privacy-validation.json").read_text())["approved"]
    assert len(list(execution.glob("privacy-validation-*.json"))) == 2
    with Session(queue.engine) as session:
        assert session.get(Asset, aid).quality["privacy_review"]["decision"] == "pending"


@DB
def test_分割目視の再取込は別画像の判定変更を承認で見落とさない(queue, legacy_managed, tmp_path):
    from bench.issue114.privacy import digest, import_reviews, save

    aid, image = legacy_managed
    with Session(queue.engine) as session, session.begin():
        source = session.get(Asset, aid)
        extra = Asset(source_id=source.source_id, url="https://example.test/extra",
                      sha256="b" * 64, storage_path=str(image), domain="real_building",
                      license_class="open", retrieved_at=datetime.now(UTC),
                      taxonomy_version="0.1.0", scene_attributes={}, quality={})
        session.add(extra)
        session.flush()
        other = extra.id
        for value in (aid, other):
            retention.review_privacy(session, value, reviewer="auto:v2", subject="building",
                                     method="person-v2", thresholds={"mask_max": .01},
                                     evidence={"input_sha256": digest(image)})
    execution = tmp_path / "execution"
    execution.mkdir()
    save(execution / "privacy-decisions.json", [
        {"asset_id": str(value), "decision": "accepted", "subject": "building", "person_ratio": 0}
        for value in (aid, other)
    ])
    save(execution / "review-manifest.json", {
        "required_ids": [str(aid)], "rows": [{"asset_id": str(value)} for value in (aid, other)],
    })
    result = {"reviewer": "目視者", "confirm_no_errors": False,
              "decisions_sha256": digest(execution / "privacy-decisions.json"), "rows": [{
                  "asset_id": str(other), "decision": "pending", "subject": "building",
                  "error_found": True, "note": "保留",
              }]}
    source = tmp_path / "review.json"
    source.write_text(json.dumps(result))
    import_reviews(queue.engine, execution, source)
    result.update(confirm_no_errors=True, rows=[{
        "asset_id": str(aid), "decision": "same", "subject": "building",
        "error_found": False, "note": "確認済み",
    }])
    source.write_text(json.dumps(result))
    import_reviews(queue.engine, execution, source)
    validation = json.loads((execution / "privacy-validation.json").read_text())
    assert not validation["approved"] and validation["requires_reanalysis"]


@DB
def test_会話の問題番号は人の履歴を残し統計承認を取り消す(queue, legacy_managed, tmp_path):
    from bench.issue114.mobile import reply_reviews
    from bench.issue114.privacy import digest, import_reviews, save

    aid, image = legacy_managed
    execution = tmp_path / "execution"
    execution.mkdir()
    row = {"asset_id": str(aid), "decision": "accepted", "subject": "building",
           "input_path": str(image), "person_ratio": 0}
    save(execution / "privacy-decisions.json", [row])
    manifest = execution / "review-manifest.json"
    save(manifest, {"required_ids": [str(aid)], "rows": [{
        "asset_id": str(aid), "decision": "accepted", "subject": "building"}]})
    mapping = {"format": "issue114-mobile-v1", "review_manifest_sha256": digest(manifest),
               "decisions_sha256": digest(execution / "privacy-decisions.json"),
               "rows": [row | {"number": 1}]}
    with Session(queue.engine) as session, session.begin():
        retention.review_privacy(session, aid, reviewer="auto:v2", subject="building",
                                 method="person-v2", thresholds={"mask_max": .01},
                                 evidence={"input_sha256": digest(image)})
    reply = {"all_reviewed": True, "reply_text": "全1枚確認、問題なし", "problems": []}
    source = tmp_path / "chat-review.json"
    for problems in ([], [{"number": 1, "reason": "人物の見落とし"}]):
        reply.update(problems=problems, reply_text="全1枚確認済み。" + str(problems))
        source.write_text(json.dumps(reply_reviews(
            mapping, manifest, mapping["decisions_sha256"], reply)))
        import_reviews(queue.engine, execution, source)
        approval = json.loads((execution / "privacy-validation.json").read_text())
        assert approval["approved"] == (not problems)
    with Session(queue.engine) as session:
        quality = session.get(Asset, aid).quality
        assert quality["privacy_review"]["reviewer"] == "ユーザー"
        assert quality["privacy_review"]["decision"] == "pending"
        assert quality["privacy_review"]["note"] == "人物の見落とし"
        assert len(quality["privacy_review_history"]) == 2


@DB
def test_目視HTMLの画像複製は非公開modeと保持台帳を固定する(queue, managed, tmp_path):
    import stat

    from bench.issue114.privacy import digest, review_bundle, save

    aid, image = managed
    execution, output = tmp_path / "execution", tmp_path / "review"
    execution.mkdir()
    mask = tmp_path / "people.png"
    Image.new("L", (8, 8), 0).save(mask)
    save(execution / "policy.json", {"mask_max": .01})
    save(execution / "privacy-decisions.json", [{
        "asset_id": str(aid), "decision": "accepted", "subject": "building",
        "reason": "person_not_detected", "person_ratio": 0, "mask_ratio": 0,
        "input_path": str(image), "mask_path": str(mask),
    }])
    with Session(queue.engine) as session, session.begin():
        record = session.get(Asset, aid)
        record.sha256 = digest(image)
        record.storage_path = str(tmp_path / "unmounted-original.jpg")
    review_bundle(queue.engine, execution, output,
                  {str(aid): {"path": str(image), "sha256": digest(image)}})
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in output.rglob('*')
               if path.is_file())
    with Session(queue.engine) as session:
        records = session.scalars(select(RetentionFile).where(
            RetentionFile.path.like(str(output) + '/%'))).all()
        assert len(records) == 5 and all(record.kind == "cache" for record in records)
    assert json.loads((output / "manifest.json").read_text())["random_ids"] == [str(aid)]


@DB
def test_停止後の依存索引再生成と公開拒否は旧版を変更しない(queue, managed):
    aid, _ = managed
    selection = {"assets": [{"asset_id": str(aid)}], "taxonomy_version": "0.1.0"}
    original = copy.deepcopy(selection)
    with Session(queue.engine) as session, session.begin():
        image = session.get(Asset, aid)
        image.search_provider = "test"
        image.quality = {**image.quality, "metadata": {"native_id": "123"}}
        retention.stop(session, provider="test", native_id="123", request_url=ISSUE)
        assert retention.rebuild_selection(session, selection)["assets"] == []
        with pytest.raises(PermissionError):
            validate_public(PUBLIC, session=session, selection=selection)
    assert selection == original


@DB
def test_参照解除DB失敗なら物理削除へ進まない(queue, managed, monkeypatch):
    _, path = managed
    with Session(queue.engine) as session, session.begin():
        session.scalar(select(Retention)).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    flush = Session.flush

    def fail_release(self, *args, **kwargs):
        if any(isinstance(row, RetentionFile) and row.released_at for row in self.dirty):
            raise RuntimeError("参照解除の注入失敗")
        return flush(self, *args, **kwargs)

    monkeypatch.setattr(Session, "flush", fail_release)
    with pytest.raises(RuntimeError), Session(queue.engine) as session, session.begin():
        retention.cleanup(session, host="test")
    assert path.exists()


@DB
def test_短いsource期限とbackup期限前の保護(queue, managed, tmp_path):
    aid, _ = managed
    backup = tmp_path / "backup.tar"
    backup.write_bytes(b"private fixture")
    now = datetime.now(UTC)
    with Session(queue.engine) as session, session.begin():
        retention.register_file(session, aid, "test", backup, "backup")
        image = session.get(Asset, aid)
        image.quality = {**image.quality, "source_policy": {
            "retention": {"deletion_request_days": 1, "backup_days": 2},
        }}
        retention.stop(session, url=image.url, request_url=ISSUE, now=now)
        record = session.scalar(select(Retention))
        assert record.expires_at == now + timedelta(days=1)
        assert record.backup_until == now + timedelta(days=2)
        retention.cleanup(session, host="test", now=now + timedelta(days=1, hours=1))
        assert backup.exists()
    with Session(queue.engine) as session, session.begin():
        retention.cleanup(session, host="test", now=now + timedelta(days=2))
    assert not backup.exists()


@DB
def test_処理結果の登録失敗でも保持対象の出力は台帳から清掃できる(queue, managed, tmp_path):
    aid, _ = managed
    queue.enqueue("prep", aid, "e" * 64, {"host": "test"})
    claim = queue.claim(("prep",))
    target = tmp_path / "derived.jpg"
    temporary = tmp_path / ".derived.tmp"
    temporary.write_bytes(b"fixture")

    def fail(session, run):
        raise RuntimeError("結果登録の注入失敗")

    with pytest.raises(RuntimeError):
        queue.complete(claim, RunInfo("open", "test", "0.1.0", "test", {}), fail,
                       [(temporary, target)])
    with Session(queue.engine) as session, session.begin():
        file = session.scalar(select(RetentionFile).where(RetentionFile.kind == "derived"))
        path = Path(file.path)
        assert path.exists() and path.stat().st_mode & 0o777 == 0o600
        session.scalar(select(Retention)).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with Session(queue.engine) as session, session.begin():
        retention.cleanup(session, host="test")
    assert not path.exists()


@DB
def test_collect入口は削除受付済み原画像をdownload前に拒否する(
    queue, managed, tmp_path, monkeypatch,
):
    finished = []

    class Adapter:
        def search(self, request):
            return SimpleNamespace(parameters={}, next_offset=None, candidates=[SimpleNamespace(
                source_url="https://example.test/source",
                original_url="https://example.test/image",
            )])

        def download(self, candidate, target):
            pytest.fail("停止済み画像を取得してはいけません")

        def finish(self):
            finished.append(True)

    with Session(queue.engine) as session, session.begin():
        retention.stop(session, source_url="https://example.test/source", request_url=ISSUE)
    monkeypatch.setattr(stage, "adapter_for", lambda *args: Adapter())
    payload, digest = payload_for(tmp_path)
    with pytest.raises(PermissionError):
        stage.prepare(claim_for(payload, digest), database_url=queue.engine.url)
    assert finished == [True]


@DB
def test_ファイル公開の途中失敗でも確定済み台帳から再開できる(
    queue, managed, tmp_path, monkeypatch,
):
    aid, _ = managed
    queue.enqueue("prep", aid, "f" * 64, {"host": "test"})
    claim = queue.claim(("prep",))
    target = tmp_path / "derived.jpg"
    temporary = tmp_path / ".derived.tmp"
    temporary.write_bytes(b"fixture")
    replace = Path.replace

    def fail(self, *args):
        if self == temporary:
            raise OSError("公開途中の注入失敗")
        return replace(self, *args)

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError):
        queue.complete(claim, RunInfo("open", "test", "0.1.0", "test", {}), lambda s, r: None,
                       [(temporary, target)])
    with Session(queue.engine) as session:
        pending = session.scalar(select(RetentionFile).where(RetentionFile.kind == "derived"))
        assert pending and not Path(pending.path).exists()
    monkeypatch.setattr(Path, "replace", replace)
    queue.complete(claim, RunInfo("open", "test", "0.1.0", "test", {}), lambda s, r: None,
                   [(temporary, target)])


@DB
def test_原画像URL受付は同じ出典の別画像を停止しない(queue, managed, tmp_path):
    aid, _ = managed
    with Session(queue.engine) as session, session.begin():
        image = session.get(Asset, aid)
        other = Asset(**{c.name: getattr(image, c.name) for c in Asset.__table__.columns
                         if c.name != "id"})
        other.url = "https://example.test/other-image"
        other.storage_path = str(tmp_path / "other.jpg")
        session.add(other)
        session.flush()
        retention.register_asset(session, other, {}, "test")
        retention.stop(session, url=image.url, request_url=ISSUE)
        retention.assert_usable(session, other.id, images=True)
        with pytest.raises(PermissionError):
            retention.assert_usable(session, aid)
        retention.stop(session, source_url="https://example.test/source", request_url=ISSUE)
        with pytest.raises(PermissionError):
            retention.check_selection(session, {"assets": [{"asset_id": str(aid)}]})


@DB
def test_保持台帳が残るmigration巻戻しは拒否し台帳を保全する(queue, managed, monkeypatch):
    aid, _ = managed
    monkeypatch.setenv("DATABASE_URL", queue.engine.url.render_as_string(hide_password=False))
    with pytest.raises(DBAPIError, match="保持台帳"):
        command.downgrade(Config("alembic.ini"), "0006")
    with Session(queue.engine) as session:
        assert session.scalar(select(Retention).where(Retention.asset_id == aid))


PUBLIC = {"format": "color-statistics-v1", "data_license": "MIT",
          "statistics": [{"oklab": [0.5, 0.1, -0.1], "ratio": 1.0, "count": 100}],
          "provenance": {"provider_counts": {"wikimedia_commons": 100}, "policy_version": "v1",
                         "build_version": "v1", "excluded_count": 0}}


@DB
@pytest.mark.parametrize("extra", ["image", "mask", "cvat_zip", "snapshot", "author", "gps",
                                   "asset_id", "source_url"])
def test_M4の画像と個別情報混入fixtureを拒否する(queue, managed, extra):
    aid, _ = managed
    with Session(queue.engine) as session:
        selection = {"assets": [{"asset_id": str(aid)}]}
        validate_public(PUBLIC, session=session, selection=selection)
        with pytest.raises(ValueError):
            validate_public(PUBLIC | {extra: "private"}, session=session, selection=selection)
        invalid = copy.deepcopy(PUBLIC)
        invalid["statistics"][0][extra] = "private"
        with pytest.raises(ValueError):
            validate_public(invalid, session=session, selection=selection)
