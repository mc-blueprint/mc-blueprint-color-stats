import hashlib
import json
import os
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic, sleep

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from colorstats.cvat import import_cvat, prepare_draft
from colorstats.schema.models import Asset, ProcessingRun, Region
from tests.test_cvat import draft_export as draft_export
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="CIのPostgreSQL専用"
)
TAXONOMY = Path(__file__).resolve().parents[1] / "taxonomy"


@pytest.fixture
def cvat_export(queue, asset, tmp_path):
    with Session(queue.engine) as session, session.begin():
        image = session.get(Asset, asset)
        image.width = image.height = 100
    manifest = tmp_path / "selection.csv"
    manifest.write_text(
        "asset_id,filename,sha256,segment_xml,original_width,original_height\n"
        f"{asset},front.png,{'a' * 64},segment.xml,100,100\n", encoding="utf-8"
    )
    (tmp_path / "segment.xml").write_text(
        '<annotations><version>1.1</version><image name="front.png" '
        'width="100" height="100"/></annotations>', encoding="utf-8",
    )
    prepare_draft(manifest, tmp_path / "draft.xml", TAXONOMY,
                  database_url=queue.engine.url, host="test")
    archive = tmp_path / "export.zip"
    polygon = '<polygon label="wall_main" points="10,10;80,10;80,80;10,80"/>'
    with zipfile.ZipFile(archive, "w") as file:
        file.writestr(
            "annotations.xml",
            '<annotations><version>1.1</version><image name="front.png" '
            f'width="100" height="100">{polygon}{polygon}</image></annotations>',
        )
        file.writestr("images/front.png", b"test image")
    return archive, manifest, tmp_path / "masks", tmp_path / "draft.json"


def test人手領域と完了runを登録し同じZIPの再取込みを拒否する(queue, asset, cvat_export):
    archive, manifest, masks, draft = cvat_export
    url = queue.engine.url.render_as_string(hide_password=False)
    import_cvat(archive, manifest, masks, TAXONOMY, url, draft)
    with Session(queue.engine) as session:
        regions = session.scalars(select(Region)).all()
        assert len(regions) == 2
        for region in regions:
            assert region.asset_id == asset and region.label_source == "human"
            assert region.label == "wall_main" and region.confidence == 1
            assert region.bbox == [10, 10, 80, 80] and region.area_ratio == 0.49
            assert region.normalized_height is None
            run = session.get(ProcessingRun, region.processing_run_id)
            assert run.license_class == "open" and run.finished_at is not None
            assert run.failure_reason is None and run.parameters["label_source"] == "human"
            saved = json.loads((Path(run.output_paths["masks"]) / region.mask_path).read_text())
            assert saved == {
                "format": "polygon-pixels-v1",
                "points": [[10, 10], [80, 10], [80, 80], [10, 80]],
            }
    with pytest.raises(ValueError, match="登録済み"):
        import_cvat(archive, manifest, masks, TAXONOMY, url, draft)
    with Session(queue.engine) as session:
        assert session.scalar(select(func.count()).select_from(Region)) == 2
        assert session.scalar(select(func.count()).select_from(ProcessingRun)) == 1
    assert len(list(masks.rglob("*.json"))) == 3


@pytest.mark.parametrize("field,value", [("sha256", "b" * 64), ("width", 200)])
def test照合不一致ではrunもmaskも作らない(queue, asset, cvat_export, field, value):
    archive, manifest, masks, draft = cvat_export
    with Session(queue.engine) as session, session.begin():
        setattr(session.get(Asset, asset), field, value)
    with pytest.raises(ValueError, match="一致|寸法"):
        import_cvat(
            archive, manifest, masks, TAXONOMY,
            queue.engine.url.render_as_string(hide_password=False), draft,
        )
    with Session(queue.engine) as session:
        assert session.scalar(select(func.count()).select_from(ProcessingRun)) == 0
        assert session.scalar(select(func.count()).select_from(Region)) == 0
    assert not list(masks.rglob("*.json"))


def test保存途中の失敗では作成済みmaskとDB変更を戻す(queue, cvat_export, monkeypatch):
    archive, manifest, masks, draft = cvat_export
    from colorstats import cvat

    dump = cvat.json.dump
    writes = 0

    def fail_second(value, file, *args, **kwargs):
        nonlocal writes
        result = dump(value, file, *args, **kwargs)
        if str(file.name).isdigit():
            writes += 1
            if writes == 2:
                raise OSError("保存失敗")
        return result

    monkeypatch.setattr(cvat.json, "dump", fail_second)
    with pytest.raises(OSError, match="保存失敗"):
        import_cvat(
            archive, manifest, masks, TAXONOMY,
            queue.engine.url.render_as_string(hide_password=False), draft,
        )
    assert writes == 2 and not list(masks.rglob("*.json"))
    with Session(queue.engine) as session:
        assert session.scalar(select(func.count()).select_from(ProcessingRun)) == 0
        assert session.scalar(select(func.count()).select_from(Region)) == 0


def test縮小下書きと差分を保持して原画像のhumanを別runへ登録する(queue, asset, draft_export):
    archive, manifest, draft = draft_export
    content = manifest.read_text()
    rows = content.splitlines()
    previous_id = rows[1].split(",")[0]
    manifest.write_text(content.replace(previous_id, str(asset)))
    baseline = json.loads(draft.read_text())
    baseline["images"]["front.png"]["asset_id"] = str(asset)
    draft.write_text(json.dumps(baseline))
    with Session(queue.engine) as session, session.begin():
        image = session.get(Asset, asset)
        image.width, image.height = 200, 300
    masks = draft.parent / "masks"
    import_cvat(archive, manifest, masks, TAXONOMY,
                queue.engine.url.render_as_string(hide_password=False), draft)
    with Session(queue.engine) as session:
        region = session.scalar(select(Region))
        assert region.label_source == "human" and region.bbox == [20, 30, 160, 240]
        assert region.area_ratio == 0.49 and region.instance_id == "cvat:0:0"
        run = session.get(ProcessingRun, region.processing_run_id)
        saved = json.loads(Path(run.output_paths["draft"]).read_text())
        assert saved == baseline and saved["label_source"] == "model"
        change = run.parameters["annotation_diff"]["front.png"][0]
        assert change["label_changed"] and change["area_pixels_delta"] == 14400
        assert run.parameters["draft_sha256"]


def test同じZIPの並行取込みは片方だけ登録する(queue, cvat_export):
    archive, manifest, masks, draft = cvat_export
    url = queue.engine.url.render_as_string(hide_password=False)
    digest = hashlib.sha256(archive.read_bytes()).digest()
    key = int.from_bytes(digest[:4], signed=True)
    with ThreadPoolExecutor(max_workers=2) as executor:
        with queue.engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(text("SELECT pg_advisory_xact_lock(41, :key)"), {"key": key})
            futures = [executor.submit(import_cvat, archive, manifest, masks, TAXONOMY, url, draft)
                       for _ in range(2)]
            try:
                deadline = monotonic() + 10
                while True:
                    waiting = connection.scalar(text(
                        "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                        "AND classid = 41 AND objid = :key AND objsubid = 2 AND NOT granted "
                        "AND database = (SELECT oid FROM pg_database "
                        "WHERE datname = current_database())"
                    ), {"key": int.from_bytes(digest[:4])})
                    if waiting == 2:
                        break
                    assert monotonic() < deadline, "両取込みがZIPの排他を待機しませんでした"
                    sleep(0.01)
            finally:
                transaction.rollback()
        errors = [future.exception(timeout=10) for future in futures]
    assert sum(error is None for error in errors) == 1
    rejected = next(error for error in errors if error is not None)
    assert isinstance(rejected, ValueError) and "登録済み" in str(rejected)
    with Session(queue.engine) as session:
        assert session.scalar(select(func.count()).select_from(ProcessingRun)) == 1
        assert session.scalar(select(func.count()).select_from(Region)) == 2
    assert len(list(masks.rglob("*.json"))) == 3
