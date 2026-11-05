import os
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from colorstats import cvat, retention
from colorstats.collect import stage
from colorstats.schema.models import (
    Asset,
    ProcessingRun,
    Region,
    Retention,
    RetentionFile,
    RetentionStop,
)
from tests.test_cvat_db import TAXONOMY
from tests.test_cvat_db import cvat_export as cvat_export
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="隔離PostgreSQL16専用",
)
ISSUE = "https://github.com/mc-blueprint/mc-blueprint-color-stats/issues/88"


@pytest.fixture(autouse=True)
def clear_stops(queue):
    with queue.engine.begin() as connection:
        connection.execute(RetentionStop.__table__.delete())


@pytest.fixture
def managed_cvat(queue, asset, cvat_export, tmp_path):
    raw = tmp_path / "raw.jpg"
    raw.write_bytes(b"fixture")
    with Session(queue.engine) as session, session.begin():
        image = session.get(Asset, asset)
        image.storage_path = str(raw)
        retention.register_asset(session, image, {}, "test")
    return cvat_export


@pytest.fixture
def mixed_export(queue, asset, cvat_export, tmp_path):
    archive, manifest, masks, _ = cvat_export
    raw = tmp_path / "new.jpg"
    raw.write_bytes(b"new fixture")
    with Session(queue.engine) as session, session.begin():
        image = session.get(Asset, asset)
        other = Asset(**{c.name: getattr(image, c.name) for c in Asset.__table__.columns
                         if c.name != "id"})
        other.url = "https://example.test/new-image"
        other.storage_path = str(raw)
        other.search_provider = "test"
        other.quality = {"metadata": {"native_id": "new"}}
        session.add(other)
        session.flush()
        retention.register_asset(session, other, {}, "test")
        new_id = other.id
    with manifest.open("a", encoding="utf-8") as file:
        file.write(f"{new_id},other.png,{'a' * 64},segment.xml,100,100\n")
    output = tmp_path / "mixed.xml"
    cvat._write_draft(manifest, output, TAXONOMY)
    with zipfile.ZipFile(archive) as file:
        xml = file.read("annotations.xml").decode()
    image = xml[xml.index("<image"):xml.index("</image>") + len("</image>")]
    with zipfile.ZipFile(archive, "w") as file:
        file.writestr("annotations.xml", xml.replace("</annotations>", image.replace(
            "front.png", "other.png",
        ) + "</annotations>"))
        file.writestr("images/front.png", b"fixture")
        file.writestr("images/other.png", b"fixture")
    return new_id, archive, manifest, masks, output.with_suffix(".json")


@pytest.mark.parametrize("old_category", ["open", "analysis_only"])
@pytest.mark.parametrize("operation", ["draft", "import"])
def test_新旧混在CVATは書込み前に拒否して分割実行を案内する(
    queue, asset, mixed_export, old_category, operation, tmp_path,
):
    aid, archive, manifest, masks, draft = mixed_export
    with Session(queue.engine) as session, session.begin():
        session.get(Asset, asset).license_class = old_category
    output = tmp_path / "blocked.xml"
    with Session(queue.engine) as session:
        before = set(session.scalars(select(RetentionFile.path)))
    with pytest.raises(ValueError, match="混在.*分けて実行"):
        if operation == "draft":
            cvat.prepare_draft(manifest, output, TAXONOMY, database_url=queue.engine.url)
        else:
            cvat.import_cvat(archive, manifest, masks, TAXONOMY, queue.engine.url, draft)
    assert not output.exists() and not output.with_suffix(".json").exists()
    assert not masks.exists()
    assert all(path.exists() for path in [archive, manifest, draft])
    with Session(queue.engine) as session:
        assert not session.scalar(select(ProcessingRun))
        assert not session.scalar(select(Region))
        assert set(session.scalars(select(RetentionFile.path))) == before


@pytest.mark.parametrize("managed", [True, False])
def test_単一保持区分のCVAT生成取込みは成功し新規だけ台帳登録する(
    queue, asset, cvat_export, tmp_path, managed,
):
    archive, manifest, masks, _ = cvat_export
    if managed:
        with Session(queue.engine) as session, session.begin():
            retention.register_asset(session, session.get(Asset, asset), {}, "test")
    output = tmp_path / "single.xml"
    cvat.prepare_draft(manifest, output, TAXONOMY, database_url=queue.engine.url, host="test")
    draft = output.with_suffix(".json")
    cvat.import_cvat(archive, manifest, masks, TAXONOMY, queue.engine.url, draft, host="test")
    with Session(queue.engine) as session:
        run = session.scalar(select(ProcessingRun))
        assert run and session.scalar(select(Region))
        paths = {str(p.resolve()) for p in [output, draft, archive, manifest]}
        paths.add(run.output_paths["draft"])
        paths.update(str(p.resolve()) for p in masks.rglob("*.json"))
        indexed = set(session.scalars(select(RetentionFile.path)))
        assert paths <= indexed if managed else not indexed
        assert all(Path(path).exists() for path in paths)


def test_CVAT相対mask参照を解除して新規画像のmaskを期限削除する(queue, managed_cvat):
    archive, manifest, masks, draft = managed_cvat
    cvat.import_cvat(archive, manifest, masks, TAXONOMY, queue.engine.url, draft, host="test")
    with Session(queue.engine) as session, session.begin():
        paths = [masks / r.mask_path for r in session.scalars(select(Region))]
        assert all(path.exists() for path in paths)
        session.scalar(select(Retention)).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with Session(queue.engine) as session, session.begin():
        retention.cleanup(session, host="test")
        assert all(r.mask_path is None for r in session.scalars(select(Region)))
        assert all(f.deleted_at for f in session.scalars(select(RetentionFile)))
    assert all(not path.exists() for path in paths)


@pytest.mark.parametrize("state", ["stopped", "expired"])
def test_prepare_draftは停止済みと期限切れを生成前に拒否する(
    queue, asset, managed_cvat, tmp_path, state,
):
    _, manifest, _, _ = managed_cvat
    with Session(queue.engine) as session, session.begin():
        if state == "stopped":
            retention.stop(session, url=session.get(Asset, asset).url, request_url=ISSUE)
        else:
            session.scalar(select(Retention)).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    output = tmp_path / "blocked.xml"
    with pytest.raises(PermissionError):
        cvat.prepare_draft(manifest, output, TAXONOMY, database_url=queue.engine.url)
    assert not output.exists() and not output.with_suffix(".json").exists()


def test_prepare_draft生成XMLとJSONを台帳へ登録して期限清掃する(queue, managed_cvat, tmp_path):
    _, manifest, _, _ = managed_cvat
    output = tmp_path / "managed.xml"
    cvat.prepare_draft(manifest, output, TAXONOMY, database_url=queue.engine.url, host="test")
    with Session(queue.engine) as session, session.begin():
        assert {str(output), str(output.with_suffix(".json"))} <= set(session.scalars(select(
            RetentionFile.path,
        )))
        session.scalar(select(Retention)).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with Session(queue.engine) as session, session.begin():
        retention.cleanup(session, host="test")
    assert not output.exists() and not output.with_suffix(".json").exists()


def test_DB未指定なら収集も下書き生成も入出力前に拒否する(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        stage.prepare(SimpleNamespace(payload={}))
    with pytest.raises(ValueError, match="DATABASE_URL"):
        cvat.prepare_draft(tmp_path / "missing.csv", tmp_path / "out.xml", TAXONOMY)


@pytest.mark.parametrize("selector", ["url", "native_id"])
def test_画像停止が同じ出典の別画像の取得を拒否しない(queue, asset, mixed_export, selector):
    aid, *_ = mixed_export
    with Session(queue.engine) as session, session.begin():
        image = session.get(Asset, aid)
        target = {"url": image.url} if selector == "url" else {
            "provider": "test", "native_id": "new",
        }
        retention.stop(session, **target, request_url=ISSUE)
    with Session(queue.engine) as session:
        old = session.get(Asset, asset)
        retention.check_acquisition(session, "test", "https://example.test/source", old.url)
        with pytest.raises(PermissionError):
            retention.check_acquisition(session, "test", "https://example.test/source",
                                        "https://example.test/new-image")


def test_CVATは公開ディレクトリとumask022でも書込み前から0600にする(
    queue, managed_cvat, monkeypatch,
):
    archive, manifest, masks, draft = managed_cvat
    masks.mkdir(mode=0o755)
    modes = []
    dump = cvat.json.dump

    def inspect_mode(value, file, *args, **kwargs):
        modes.append(os.fstat(file.fileno()).st_mode & 0o777)
        assert modes[-1] == 0o600
        return dump(value, file, *args, **kwargs)

    monkeypatch.setattr(cvat.json, "dump", inspect_mode)
    previous = os.umask(0o022)
    try:
        cvat.import_cvat(archive, manifest, masks, TAXONOMY, queue.engine.url, draft, host="test")
    finally:
        os.umask(previous)
    assert len(modes) == 3
