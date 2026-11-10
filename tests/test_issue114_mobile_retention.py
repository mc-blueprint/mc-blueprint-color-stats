import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from bench.issue114 import mobile
from bench.issue114.mobile import build
from bench.issue114.privacy import digest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from colorstats import retention
from colorstats.schema.models import Asset, Retention, RetentionFile
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue
from tests.test_retention import managed as managed

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="隔離PostgreSQL専用",
)
ROOT = Path(__file__).resolve().parents[1]


def inputs(tmp_path, managed):
    aid, raw = managed
    bundle, execution = tmp_path / "bundle", tmp_path / "execution"
    (bundle / "images").mkdir(parents=True)
    execution.mkdir()
    Image.open(raw).save(bundle / "images" / f"{aid}-raw.png")
    mask = tmp_path / "person.png"
    Image.new("L", (8, 8)).save(mask)
    row = {"asset_id": str(aid), "region_run_id": str(uuid4()), "input_path": str(raw),
           "input_sha256": digest(raw), "mask_path": str(mask), "mask_sha256": digest(mask),
           "decision": "accepted", "subject": "building", "reason": "person_not_detected",
           "person_ratio": 0, "mask_ratio": 0}
    decisions = execution / "privacy-decisions.json"
    decisions.write_text(json.dumps([row]))
    (bundle / "manifest.json").write_text(json.dumps({
        "required_ids": [str(aid)], "random_ids": [str(aid)], "boundary_ids": [],
        "decisions_sha256": digest(decisions),
    }))
    return bundle, execution, tmp_path / "mobile"


def test_A_B契約のない既存判定では本番用HTMLを生成しない(queue, managed, tmp_path):
    bundle, execution, output = inputs(tmp_path, managed)
    with pytest.raises(ValueError, match="image-review-v1"):
        build(queue.engine, bundle, execution, output, ROOT / "taxonomy")
    assert not output.exists()


@pytest.mark.parametrize("state", ["stopped", "expired"])
def test_停止または期限切れ画像はモバイルHTMLを生成しない(queue, managed, tmp_path, state):
    bundle, execution, output = inputs(tmp_path, managed)
    with Session(queue.engine) as session, session.begin():
        record = session.scalar(select(Retention))
        if state == "stopped":
            record.stopped_at = datetime.now(UTC)
        else:
            record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(PermissionError):
        build(queue.engine, bundle, execution, output, ROOT / "taxonomy")
    assert not output.exists()


def test_HTMLと番号表は保持台帳へ登録され期限後の管理対象となる(queue, managed, tmp_path):
    bundle, execution, output = inputs(tmp_path, managed)
    build(queue.engine, bundle, execution, output, ROOT / "taxonomy", require_contracts=False)
    with Session(queue.engine) as session, session.begin():
        files = session.scalars(select(RetentionFile).where(
            RetentionFile.path.in_([str(p.resolve()) for p in output.iterdir()]),
        )).all()
        assert {Path(file.path).name for file in files} == {"review-01.html", "number-map.json"}
        assert all(file.asset_id == managed[0] and file.kind == "image_bundle" for file in files)
        host = files[0].host
        session.scalar(select(Retention)).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with Session(queue.engine) as session, session.begin():
        retention.cleanup(session, host=host)
    assert not list(output.iterdir())


@pytest.fixture
def shared_mobile(queue, managed, tmp_path):
    bundle, execution, output = inputs(tmp_path, managed)
    raw = tmp_path / "other.png"
    Image.new("RGB", (8, 8), "blue").save(raw)
    with Session(queue.engine) as session, session.begin():
        original = session.get(Asset, managed[0])
        other = Asset(**{column.name: getattr(original, column.name)
                         for column in Asset.__table__.columns if column.name != "id"})
        other.url += "/other"
        other.storage_path = str(raw)
        other.sha256 = digest(raw)
        session.add(other)
        session.flush()
        retention.register_asset(session, other, {}, "test")
        other_id = other.id
    decisions = execution / "privacy-decisions.json"
    rows = json.loads(decisions.read_text())
    rows.append(rows[0] | {"asset_id": str(other_id), "input_path": str(raw),
                           "input_sha256": digest(raw)})
    decisions.write_text(json.dumps(rows))
    Image.open(raw).save(bundle / "images" / f"{other_id}-raw.png")
    manifest = bundle / "manifest.json"
    manifest.write_text(json.dumps({
        "required_ids": [row["asset_id"] for row in rows],
        "random_ids": [row["asset_id"] for row in rows], "boundary_ids": [],
        "decisions_sha256": digest(decisions),
    }))
    return bundle, execution, output, other_id, raw


@pytest.mark.parametrize("state", ["expired", "stopped", "deletion"])
def test_画像束は構成画像一件の失効で全体を削除し通常の共有ファイルは保護する(
    queue, managed, shared_mobile, tmp_path, state,
):
    bundle, execution, output, other_id, raw = shared_mobile
    build(queue.engine, bundle, execution, output, ROOT / "taxonomy", host="review-test",
          require_contracts=False)
    shared = tmp_path / "ordinary-cache.bin"
    shared.write_bytes(b"shared")
    with Session(queue.engine) as session, session.begin():
        retention.lock(session)
        for aid in (managed[0], other_id):
            retention.register_file(session, aid, "review-test", shared, "cache")
        record = session.scalar(select(Retention).where(Retention.asset_id == managed[0]))
        if state == "expired":
            record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        elif state == "stopped":
            record.stopped_at = datetime.now(UTC)
        else:
            retention.stop(session, url=session.get(Asset, managed[0]).url,
                           request_url="https://github.com/mc-blueprint/"
                           "mc-blueprint-color-stats/issues/114")
    with Session(queue.engine) as session, session.begin():
        retention.cleanup(session, host="review-test")
        retention.assert_usable(session, other_id, images=True)
        files = session.scalars(select(RetentionFile).where(
            RetentionFile.path.in_([str(output / "review-01.html"),
                                    str(output / "number-map.json")]),
        )).all()
        assert len(files) == 4 and all(file.released_at and file.deleted_at for file in files)
    assert not list(output.iterdir())
    assert shared.exists() and raw.exists()


def test_単一HTMLは構成画像の一件失効で削除し原画像は保持する(
    queue, managed, shared_mobile,
):
    bundle, execution, output, other_id, raw = shared_mobile
    build(queue.engine, bundle, execution, output, ROOT / "taxonomy", host="review-test",
          require_contracts=False)
    mapping = json.loads((output / "number-map.json").read_text())
    assert len(mapping["files"]) == 1
    with Session(queue.engine) as session, session.begin():
        session.scalar(select(Retention).where(
            Retention.asset_id == managed[0],
        )).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with Session(queue.engine) as session, session.begin():
        retention.cleanup(session, host="review-test")
    assert not (output / mapping["files"][0]["file"]).exists()
    assert not (output / "number-map.json").exists()
    assert raw.exists()


def test_分割HTMLは各ページの対象だけを保持登録し番号表は全対象へ登録する(
    queue, managed, shared_mobile, monkeypatch,
):
    bundle, execution, output, other_id, raw = shared_mobile
    write = mobile.write_pages

    def split(cards, output, *, group_counts):
        header = len(mobile.page([], 1, 2, 2, group_counts,
                                 legend=mobile._legend(cards)).encode())
        return write(cards, output, limit=header + max(len(c.encode()) for c in cards) + 20,
                     group_counts=group_counts)

    monkeypatch.setattr(mobile, "write_pages", split)
    build(queue.engine, bundle, execution, output, ROOT / "taxonomy", host="review-test",
          require_contracts=False)
    mapping = json.loads((output / "number-map.json").read_text())
    assert len(mapping["files"]) == 2
    with Session(queue.engine) as session:
        for item in mapping["files"]:
            actual = set(session.scalars(select(RetentionFile.asset_id).where(
                RetentionFile.path == str(output / item["file"]))))
            expected = {UUID(row["asset_id"]) for row in
                        mapping["rows"][item["first"] - 1:item["last"]]}
            assert actual == expected
        actual = set(session.scalars(select(RetentionFile.asset_id).where(
            RetentionFile.path == str(output / "number-map.json"))))
        assert actual == {managed[0], other_id}
