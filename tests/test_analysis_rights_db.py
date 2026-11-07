import copy
import os
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest
from alembic import command
from alembic.config import Config
from PIL import Image
from sqlalchemy import delete, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from colorstats.analyze import color, prep, segment, shade
from colorstats.collect import Candidate, SearchResult, measurement
from colorstats.collect import stage as collect
from colorstats.queue import RunInfo
from colorstats.retention import review_privacy
from colorstats.schema.models import Asset, ProcessingRun, Retention, RetentionFile, Source, Subject
from colorstats.stats import aggregate, subjects
from colorstats.stats.snapshot import execute
from colorstats.stats.subject_cli import load_rules
from tests.test_analysis_rights import analysis_policy as analysis_policy
from tests.test_collect import payload_for
from tests.test_cvat_db import cvat_export as cvat_export
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue
from tests.test_segment import payload as payload
from tests.test_segment import prediction
from tests.test_stats_aggregate import settings as settings
from tests.test_stats_snapshot_db import QUALITY

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="隔離PostgreSQL16専用",
)


@pytest.mark.parametrize("category", ["analysis_only", "open"])
def test_旧cohortのsubjectと全stageを経由して統計へ区分と根拠が伝播する(
    queue, tmp_path, analysis_policy, payload, settings, monkeypatch, category,
):
    with Session(queue.engine) as session, session.begin():
        session.execute(delete(Subject))
    license_name = "all rights reserved" if category == "analysis_only" else "cc0"

    class Adapter:
        def search(self, request):
            return SearchResult([Candidate(
                source_url="https://fixture.test/item/1", original_url="https://fixture.test/1.jpg",
                rank=0, page=0, title="Dome of the Rock", author=None, license=license_name,
                license_url=None, description=None, location=None, width=8, height=6,
                mime="image/jpeg",
                metadata={"categories": [{"title": "Category:Facade of the Dome of the Rock"}]},
                attribution="fixture.test/item/1 | CC0" if category == "open" else None,
            )], {})

        def download(self, candidate, target):
            Image.new("RGB", (8, 6), "orange").save(target, format="JPEG")

        def finish(self):
            pass

    monkeypatch.setattr(collect, "adapter_for", lambda *args: Adapter())
    collection, _ = payload_for(tmp_path)
    if category == "open":
        analysis_policy["license_rules"] = {"open": ["cc0"]}
    collection["policy"] = analysis_policy
    queue.enqueue("collect", None, "a" * 64, collection)
    claim = queue.claim(("collect",))
    result = collect.prepare(claim, database_url=queue.engine.url)
    run_id = queue.complete(
        claim, result.info, lambda s, r: collect.register(s, r, result.data), result.files,
    )
    with Session(queue.engine) as session:
        image = session.scalars(select(Asset)).one()
        asset_id, raw_path = image.id, image.storage_path
        assert image.license_class == category
        if category == "analysis_only":
            assert image.quality["rights"]["rights_review"] == analysis_policy["rights_review"]
            assert image.quality["original_id"] == "https://fixture.test/item/1"
        assert session.get(ProcessingRun, run_id).license_class == category
        source_id = image.source_id
    with Session(queue.engine) as session, session.begin():
        trial = ProcessingRun(
            stage="collect", license_class="restricted", config_hash="d" * 64,
            parameters={"counts": {}}, code_version="fixture", taxonomy_version="0.1.0",
            node="test",
        )
        session.add(trial)
        session.flush()
        measurement.record(session, session.get(ProcessingRun, run_id),
                           {**result.data, "measurement_run_id": str(trial.id)}, set())
        assert trial.parameters["counts"]["eligible_new_sha"] == 1
        assert trial.parameters["d15_exclusions"] == {}
    # 同じ出典で後日の異なる権利が届いても初回sourceを更新しない。
    changed = copy.deepcopy(result.data)
    changed["records"][0]["candidate"]["license"] = "cc0"
    changed["records"][0]["license_class"] = "open"
    with Session(queue.engine) as session, session.begin():
        collect.register(session, session.get(ProcessingRun, run_id), changed)
        assert session.get(Source, source_id).license == license_name

    rules = load_rules(Path("configs/subject_rules.yaml"), Path("taxonomy"))
    inferred = subjects.execute(
        queue.engine, rules, tmp_path / "subjects.json", code_version="test",
    )
    subject_run_id = inferred["run_id"]
    with Session(queue.engine) as session:
        image = session.get(Asset, asset_id)
        assert image.subject_id is not None
        assert image.quality["subject_inference"]["run_id"] == subject_run_id
        assert image.quality["subject_inference"]["state"] == "confirmed"
        assert session.get(ProcessingRun, subject_run_id).license_class == category

    def complete_stage(module, name, config):
        digest = module.config_hash(config) if hasattr(module, "config_hash") else "b" * 64
        queue.enqueue(name, asset_id, digest, config)
        job = queue.claim((name,))
        prepared = module.prepare(job)
        rid = queue.complete(
            job, prepared.info, lambda s, r: module.register(s, r, prepared.data), prepared.files,
        )
        with Session(queue.engine) as session:
            saved = session.get(ProcessingRun, rid)
            assert saved.license_class == category
            return str(rid), dict(saved.output_paths)

    prep_id, outputs = complete_stage(prep, "prep", {
        "input_path": raw_path, "derived_path": str(tmp_path / "prep.jpg"),
        "license_class": "open", "taxonomy_version": "0.1.0",
    })
    payload.update(input_path=outputs[str(tmp_path / "prep.jpg")], input_run_id=prep_id,
                   license_class=category, threshold=0.35, text_threshold=0.25)
    monkeypatch.setattr(segment, "predict", prediction)
    segment_id, _ = complete_stage(segment, "segment", payload)
    with Session(queue.engine) as session:
        regions = color.region_inputs(session, asset_id, segment_id)
    base = {"input_path": payload["input_path"], "input_run_id": prep_id,
            "region_run_id": segment_id, "regions": regions, "license_class": category,
            "taxonomy_version": "0.1.0", "output_path": str(tmp_path / "shade.json")}
    with Session(queue.engine) as session, session.begin():
        # 旧cohortの権利伝播を検証し、新規画像の人物確認とは分ける。
        session.execute(delete(RetentionFile).where(RetentionFile.asset_id == asset_id))
        session.execute(delete(Retention).where(Retention.asset_id == asset_id))
        review_privacy(session, asset_id, reviewer="fixture", subject="building")
    complete_stage(shade, "shade", base | {"method": "none"})
    color_id, _ = complete_stage(color, "color", base | {
        "output_path": str(tmp_path / "color.json"),
    })
    selection = {"taxonomy_version": "0.1.0", "assets": [{
        "asset_id": str(asset_id), "prep_run_id": prep_id,
        "segment_run_id": segment_id, "color_run_id": color_id,
    }]}
    quality = copy.deepcopy(QUALITY)
    quality["segment"] = {key: payload[key] for key in QUALITY["segment"]}
    output = tmp_path / "snapshot"
    manifest = execute(queue.engine, selection, output, quality=quality, code_version="fixture")
    assert manifest["format_version"] == 2 and manifest["access_scope"] == "internal"
    assert manifest["counts"]["rights_eligible"] == 1
    with duckdb.connect() as db:
        assert db.execute("SELECT eligible FROM read_parquet(?)", [
            str(output / "assets.parquet"),
        ]).fetchone() == (True,)
        assert db.execute("SELECT count(*) FROM read_parquet(?) WHERE id = ?", [
            str(output / "runs.parquet"), subject_run_id,
        ]).fetchone() == (1,)
        assert db.execute("SELECT reasons FROM read_parquet(?)", [
            str(output / "assets.parquet"),
        ]).fetchone() == ("[]",)
    config = {"snapshot": str(output), "snapshot_id": manifest["snapshot_id"],
              "settings": settings, "output_path": str(tmp_path / "aggregate.json")}
    queue.enqueue("aggregate", None, aggregate.config_hash(config), config)
    job = queue.claim(("aggregate",))
    prepared = aggregate.prepare(job)
    assert prepared.info.license_class == category
    aggregate_id = queue.complete(
        job, prepared.info, lambda s, r: aggregate.register(s, r, prepared.data), prepared.files,
    )
    with Session(queue.engine) as session:
        assert session.get(ProcessingRun, aggregate_id).license_class == category
        assert any(row["id"] == subject_run_id for row in prepared.data["input_runs"])
    with Session(queue.engine) as session, session.begin():
        session.get(ProcessingRun, subject_run_id).license_class = "restricted"
    excluded = tmp_path / "restricted-subject"
    rejected = execute(queue.engine, selection, excluded, quality=quality, code_version="fixture")
    assert rejected["counts"]["rights_eligible"] == 0
    assert rejected["exclusions"]["restricted_run"] == 1
    with duckdb.connect() as db:
        assert db.execute("SELECT eligible, reasons FROM read_parquet(?)", [
            str(excluded / "assets.parquet"),
        ]).fetchone() == (False, '["restricted_run"]')


@pytest.mark.parametrize("category", ["open", "analysis_only", "noncommercial", "academic_only",
                                      "restricted"])
def test_queueはpayloadに依存せずsourceとassetの区分を保持する(queue, asset, category):
    with Session(queue.engine) as session, session.begin():
        image = session.get(Asset, asset)
        image.license_class = category
        session.get(Source, image.source_id).license_class = category
    queue.enqueue("prep", asset, "c" * 64, {})
    claim = queue.claim(("prep",))
    rid = queue.complete(claim, RunInfo("open", "fixture", "0.1.0", "test", {}), lambda s, r: None)
    with Session(queue.engine) as session:
        assert session.get(ProcessingRun, rid).license_class == category


def test_CVATは解析専用区分を保持する(queue, asset, cvat_export):
    from colorstats.cvat import import_cvat

    with Session(queue.engine) as session, session.begin():
        session.get(Asset, asset).license_class = "analysis_only"
    archive, manifest, masks, draft = cvat_export
    import_cvat(archive, manifest, masks, Path("taxonomy"),
                queue.engine.url.render_as_string(hide_password=False), draft)
    with Session(queue.engine) as session:
        assert session.scalars(select(ProcessingRun.license_class)).all() == ["analysis_only"]


def test_全CHECKと列長を確認し解析行があれば巻戻しを拒否する(database, queue, monkeypatch):
    config = Config("alembic.ini")
    monkeypatch.setenv("DATABASE_URL", database.url.render_as_string(hide_password=False))
    with database.connect() as connection:
        previous_version = connection.scalar(text("SELECT version_num FROM alembic_version"))
    for table in ("source", "asset", "processing_run"):
        check = next(c for c in inspect(database).get_check_constraints(table)
                     if c["name"] == f"ck_{table}_license_class")
        assert "analysis_only" in check["sqltext"]
        column = next(c for c in inspect(database).get_columns(table)
                      if c["name"] == "license_class")
        assert column["type"].length == 13
    with Session(database) as session, session.begin():
        session.add(Source(url="https://migration.test", site="fixture", license="ARR",
                           license_class="analysis_only", retrieved_at=datetime.now(UTC),
                           policy={}))
    with pytest.raises(DBAPIError, match="analysis_only"):
        command.downgrade(config, "0005")
    with database.begin() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert version == previous_version
        connection.execute(text("DELETE FROM source WHERE url='https://migration.test'"))
    command.downgrade(config, "0005")
    command.upgrade(config, "head")
