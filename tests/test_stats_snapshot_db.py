import copy
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import duckdb
import pytest
import yaml
from sqlalchemy import event, update
from sqlalchemy.orm import Session

from colorstats.schema.models import (
    Asset,
    ColorObservation,
    Job,
    ProcessingRun,
    ProcessingRunInput,
    Region,
    Relation,
    Source,
)
from colorstats.stats.snapshot import execute, verify
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="隔離PostgreSQL専用",
)
QUALITY = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / "configs/segment_stats.yaml").read_text(encoding="utf-8")
)

QUALITY["supported_by_domain"] = {"real_building": ["door"], "real_terrain": []}


def prepare(queue, asset):
    selection = {"taxonomy_version": "0.1.0", "assets": []}
    with Session(queue.engine) as session, session.begin():
        base = session.get(Asset, asset)
        source = session.get(Source, base.source_id)
        source.author = "作者"
        source.attribution = "作者・出典・CC0・原本"
        for index in range(1, 10):
            license_name = {3: "cc-by-sa-4.0", 4: "cc-by-nc-4.0"}.get(index, "cc0")
            origin = Source(
                url=f"https://source.test/{index}", site="fixture", author="作者",
                attribution=None if index == 6 else "作者・出典", license=license_name,
                license_class="open", retrieved_at=datetime.now(UTC), policy={},
            )
            session.add(origin)
            session.flush()
            row = Asset(
                id=UUID(int=index), source_id=origin.id, url=f"https://image.test/{index}",
                sha256=("a" if index in (1, 2, 3) else str(index)) * 64,
                storage_path="未使用", domain="real_building", license_class="open",
                retrieved_at=datetime.now(UTC), taxonomy_version="0.1.0", scene_attributes={},
                quality={"license": license_name, "author": "作者",
                         "license_url": "https://license.test"},
            )
            if index == 7:
                row.quality = {}
            session.add(row)
            session.flush()
            chosen = {"asset_id": str(row.id)}
            runs = {}
            for stage in ("prep", "segment", "color"):
                run = ProcessingRun(
                    id=uuid4(), stage=stage, license_class="open",
                    config_hash=str(index) * 64, code_version="fixture", node="test",
                    taxonomy_version="0.1.0", started_at=datetime.now(UTC),
                    finished_at=datetime.now(UTC), parameters={},
                )
                if stage == "segment":
                    run.parameters = {"payload": QUALITY["segment"]}
                if stage == "prep" and index == 5:
                    run.parameters = {"models": {"weights": {"license_class": "academic_only"}}}
                session.add(run)
                session.flush()
                session.add(Job(stage=stage, asset_id=row.id, stage_config_hash=str(index) * 64,
                                payload={}, status="succeeded", run_id=run.id))
                parents = {"segment": ["prep"], "color": ["prep", "segment"]}.get(stage, [])
                session.add_all(ProcessingRunInput(run_id=run.id, input_run_id=runs[p])
                                for p in parents)
                runs[stage] = run.id
                chosen[stage + "_run_id"] = str(run.id)
            regions = []
            for label in ("door", "wall_main"):
                region = Region(
                    asset_id=row.id, processing_run_id=runs["segment"], taxonomy_version="0.1.0",
                    label=label, bbox=[0, 0, 10, 10], label_source="model",
                    confidence=0.9, area_ratio=0.5,
                )
                session.add(region)
                session.flush()
                regions.append(region.id)
                session.add(ColorObservation(
                    region_id=region.id, processing_run_id=runs["color"],
                    observed_oklab={"dominant": [0.5, 0, 0]}, area_ratio=0.5,
                ))
            session.add(ColorObservation(
                asset_id=row.id, processing_run_id=runs["color"],
                observed_oklab={"dominant": [0.4, 0, 0]}, area_ratio=1,
            ))
            session.add(Relation(
                asset_id=row.id, processing_run_id=runs["color"], region_a=regions[0],
                region_b=regions[1], type="co_occurs", delta_l=0.1, delta_c=0,
                delta_h=None, delta_e_ok=0.1, area_ratio=1,
            ))
            if index == 8:
                chosen.pop("color_run_id")
            selection["assets"].append(chosen)
    return selection


def build(queue, selection, output, **kwargs):
    return execute(
        queue.engine, selection, output, quality=QUALITY, code_version="fixture", **kwargs,
    )


def test_fixed_snapshot_rights_duplicates_counts_and_dry_run(queue, asset, tmp_path):
    selection = prepare(queue, asset)
    dry = build(queue, selection, tmp_path / "dry", dry_run=True)
    assert not (tmp_path / "dry").exists()
    result = build(queue, selection, tmp_path / "fixed")
    assert result["counts"] == dry["counts"]
    assert result["transaction"]["isolation"] == "repeatable read"
    assert result["transaction"]["read_only"] == "on"
    assert result["counts"]["assets"] == 9
    assert result["counts"]["sha_distinct"] == 7
    assert result["counts"]["rights_eligible"] == 4
    assert result["counts"]["analysis_eligible"] == 3
    assert result["counts"]["representatives"] == 2
    assert result["exclusions"]["sha_duplicate"] == 1
    assert result["counts"]["observations_eligible"] == 2
    assert result["counts"]["relations_eligible"] == 0
    with duckdb.connect() as db:
        rows = db.execute("SELECT id, representative_id, eligible FROM read_parquet(?) ORDER BY id",
                          [str(tmp_path / "fixed/assets.parquet")]).fetchall()
        assert rows[0][1] == rows[1][1] == rows[2][1] == str(UUID(int=1))
        assert rows[0][2] and not rows[1][2] and not rows[2][2]
        assert db.execute("SELECT count(*) FROM read_parquet(?)",
                          [str(tmp_path / "fixed/provenance.parquet")]).fetchone()[0] == 9
    selection["assets"].reverse()
    again = build(queue, selection, tmp_path / "reordered")
    assert again["counts"] == result["counts"]
    assert again["files"] == result["files"]
    with queue.engine.begin() as connection:
        connection.execute(update(Source).values(attribution="DB変更後"))
    assert verify(tmp_path / "fixed", result["snapshot_id"]) == result
    with pytest.raises(FileExistsError):
        build(queue, selection, tmp_path / "fixed")


def test_repeatable_read_sees_original_attribution_during_concurrent_update(queue, asset, tmp_path):
    selection = prepare(queue, asset)
    changed = False

    def change(connection, cursor, statement, parameters, context, executemany):
        nonlocal changed
        if statement.startswith("SELECT asset.") and not changed:
            changed = True
            with queue.engine.begin() as other:
                other.execute(update(Source).values(attribution="並行更新"))
    event.listen(queue.engine, "after_cursor_execute", change)
    try:
        result = build(queue, selection, tmp_path / "fixed")
    finally:
        event.remove(queue.engine, "after_cursor_execute", change)
    assert changed
    assert result["counts"]["representatives"] == 2
    with duckdb.connect() as db:
        values = db.execute("SELECT data FROM read_parquet(?)",
                            [str(tmp_path / "fixed/provenance.parquet")]).fetchall()
    assert all(json.loads(row[0])["attribution"] != "並行更新" for row in values)


@pytest.mark.parametrize("failure", ["other_asset", "other_success", "failed", "cycle", "settings"])
def test_reject_mixed_runs_without_success_manifest(queue, asset, tmp_path, failure):
    selection = prepare(queue, asset)
    if failure == "other_asset":
        selection["assets"][0]["color_run_id"] = selection["assets"][1]["color_run_id"]
    with Session(queue.engine) as session, session.begin():
        chosen = selection["assets"][0]
        segment = session.get(ProcessingRun, UUID(chosen["segment_run_id"]))
        if failure == "failed":
            segment.failure_reason = "fixture failure"
        if failure == "settings":
            segment.parameters = {"payload": QUALITY["segment"] | {"threshold": 0.9}}
        if failure == "cycle":
            session.add(ProcessingRunInput(
                run_id=UUID(chosen["prep_run_id"]), input_run_id=segment.id,
            ))
        if failure == "other_success":
            clone = ProcessingRun(
                stage="segment", license_class="open", config_hash="f" * 64,
                parameters=copy.deepcopy(segment.parameters), code_version="test", node="test",
                taxonomy_version="0.1.0", started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            )
            session.add(clone)
            session.flush()
            session.add(Job(stage="segment", asset_id=UUID(chosen["asset_id"]),
                            stage_config_hash="f" * 64, payload={},
                            status="succeeded", run_id=clone.id))
            session.add(ProcessingRunInput(
                run_id=clone.id, input_run_id=UUID(chosen["prep_run_id"]),
            ))
            chosen["segment_run_id"] = str(clone.id)
    with pytest.raises(ValueError):
        build(queue, selection, tmp_path / "failed")
    assert not (tmp_path / "failed/manifest.json").exists()


def test_missing_and_duplicate_asset_and_output_failure(queue, asset, tmp_path, monkeypatch):
    selection = prepare(queue, asset)
    missing = copy.deepcopy(selection)
    missing["assets"][0]["asset_id"] = str(uuid4())
    with pytest.raises(ValueError, match="見つかりません"):
        build(queue, missing, None, dry_run=True)
    duplicate = copy.deepcopy(selection)
    duplicate["assets"].append(duplicate["assets"][0])
    with pytest.raises(ValueError, match="重複"):
        build(queue, duplicate, None, dry_run=True)
    parent = tmp_path / "file"
    parent.write_text("保持", encoding="utf-8")
    with pytest.raises(OSError):
        build(queue, selection, parent / "child")
    assert parent.read_text(encoding="utf-8") == "保持"
    original = Path.open

    def fail_execution(path, *args, **kwargs):
        if path.name == "execution.json":
            raise OSError("計測出力の失敗")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patcher:
        patcher.setattr(Path, "open", fail_execution)
        with pytest.raises(OSError, match="計測出力"):
            build(queue, selection, tmp_path / "execution-failed")
    assert not (tmp_path / "execution-failed/manifest.json").exists()


@pytest.mark.parametrize("excluded", [False, True])
def test_union_uses_pixels_and_freezes_colors_without_images(queue, asset, tmp_path, excluded):
    import numpy as np
    from PIL import Image
    from sqlalchemy import select

    from colorstats.analyze import color
    from colorstats.stats.snapshot_cli import load_quality

    selection = prepare(queue, asset)
    chosen = selection["assets"][0]
    selection["assets"] = [chosen]
    image = tmp_path / "image.png"
    if excluded:
        Image.new("RGB", (20, 20), (120, 80, 50)).save(image)
    else:
        pixels = np.random.default_rng(74).integers(20, 220, (20, 20, 3), dtype="uint8")
        Image.fromarray(pixels).save(image)
    with Session(queue.engine) as session, session.begin():
        segment = session.get(ProcessingRun, UUID(chosen["segment_run_id"]))
        regions = list(session.scalars(select(Region).where(
            Region.processing_run_id == segment.id,
        ).order_by(Region.id)))
        outputs = {}
        for index, region in enumerate(regions):
            pixels = np.zeros((20, 20), dtype="uint8")
            pixels[:, :15] = 255
            if index == 1:
                pixels = pixels[:, ::-1].copy()
            path = tmp_path / f"mask-{index}.png"
            Image.fromarray(pixels).save(path)
            outputs[str(path)] = str(path)
            region.mask_path = str(path)
            region.label = ("wall_main", "wall_secondary")[index]
        segment.output_paths = outputs
        segment.parameters = {"payload": QUALITY["segment"], "metrics": {"width": 20, "height": 20}}
        session.flush()
        payload = {
            "input_path": str(image), "input_run_id": chosen["prep_run_id"],
            "region_run_id": chosen["segment_run_id"],
            "regions": color.region_inputs(session, UUID(chosen["asset_id"]), segment.id),
        }
        run = session.get(ProcessingRun, UUID(chosen["color_run_id"]))
        run.parameters = {"payload": payload}
        run.config_hash = color.config_hash(payload)
    if excluded:
        from colorstats.schema.models import Subject

        with Session(queue.engine) as session, session.begin():
            target = session.get(Asset, UUID(chosen["asset_id"]))
            origin = session.get(Source, target.source_id)
            origin.license = "cc-by-sa-4.0"
            target.quality = {**target.quality, "license": origin.license}
            subject = Subject(name="除外前対象", domain="real_building",
                              taxonomy_version="0.1.0", scene_attributes={})
            session.add(subject)
            session.flush()
            target.subject_id = subject.id
    quality = load_quality(Path(__file__).resolve().parents[1] / "configs/segment_stats.yaml")
    result = execute(queue.engine, selection, tmp_path / "fixed", quality=quality,
                     code_version="fixture")
    assert result["counts"]["groups_eligible"] == (0 if excluded else 1)
    with duckdb.connect() as db:
        row = db.execute("SELECT role, data FROM read_parquet(?)",
                         [str(tmp_path / "fixed/groups.parquet")]).fetchone()
    assert row[0] == "real_building/wall"
    data = json.loads(row[1])
    assert data["area_ratio"] == 1
    assert len(data["observations"]) == (1 if excluded else 5)
    with duckdb.connect() as db:
        gate = db.execute(
            "SELECT g.eligible, g.quality_eligible, g.reasons, a.subject_id, "
            "a.rights_eligible, a.analysis_available FROM read_parquet(?) g "
            "JOIN read_parquet(?) a ON a.id = g.asset_id",
            [str(tmp_path / "fixed/groups.parquet"), str(tmp_path / "fixed/assets.parquet")],
        ).fetchone()
    assert gate[0] is not excluded
    assert gate[1] and gate[5]
    assert gate[4] is not excluded
    if excluded:
        assert gate[3]
        assert "license_conditions" in json.loads(gate[2])
    repeated = execute(queue.engine, selection, tmp_path / "repeated", quality=quality,
                       code_version="fixture")
    assert repeated["snapshot_id"] == result["snapshot_id"]
    image.unlink()
    assert verify(tmp_path / "fixed", result["snapshot_id"]) == result
    with pytest.raises(FileNotFoundError):
        execute(queue.engine, selection, tmp_path / "failure", quality=quality,
                code_version="fixture")
    assert not (tmp_path / "failure/manifest.json").exists()


def test_building_label_support_does_not_transfer_to_terrain(queue, asset, tmp_path):
    selection = prepare(queue, asset)
    chosen = selection["assets"][0]
    selection["assets"] = [chosen]
    with Session(queue.engine) as session, session.begin():
        session.get(Asset, UUID(chosen["asset_id"])).domain = "real_terrain"
    result = build(queue, selection, tmp_path / "fixed")
    assert result["counts"]["representatives"] == 1
    assert result["counts"]["observations_eligible"] == 0


def test_subject_attributes_candidates_and_all_input_rights_are_frozen(queue, asset, tmp_path):
    from colorstats.schema.models import Subject, SubjectCandidate

    selection = prepare(queue, asset)
    chosen = selection["assets"][0]
    selection["assets"] = [chosen]
    with Session(queue.engine) as session, session.begin():
        subject = Subject(name="確定対象", domain="real_building", taxonomy_version="0.1.0",
                          scene_attributes={"style": "gothic"})
        session.add(subject)
        session.flush()
        run = ProcessingRun(
            stage="subject", license_class="open", config_hash="b" * 64,
            parameters={"subject_keys": {}}, code_version="fixture", node="test",
            taxonomy_version="0.1.0", started_at=datetime.now(UTC), finished_at=datetime.now(UTC),
        )
        session.add(run)
        session.flush()
        run_id, subject_id = run.id, subject.id
        target = session.get(Asset, UUID(chosen["asset_id"]))
        target.subject_id = subject.id
        target.scene_attributes = {"style": "gothic"}
        target.quality = {**target.quality, "subject_inference": {"run_id": str(run.id)}}
        session.add(SubjectCandidate(asset_id=target.id, subject_id=subject.id, confidence=1,
                                     evidence={"run_id": str(run.id), "method": "fixture"}))
    result = build(queue, selection, tmp_path / "fixed")
    assert result["counts"]["confirmed_subjects"] == 1
    with Session(queue.engine) as session, session.begin():
        session.get(Subject, subject_id).name = "変更後"
        session.get(ProcessingRun, run_id).license_class = "academic_only"
        session.get(Asset, UUID(chosen["asset_id"])).scene_attributes = {}
    assert verify(tmp_path / "fixed", result["snapshot_id"]) == result
    with duckdb.connect() as db:
        data = json.loads(db.execute("SELECT data FROM read_parquet(?)",
                          [str(tmp_path / "fixed/assets.parquet")]).fetchone()[0])
        assert data["subject"]["name"] == "確定対象"
        assert data["scene_attributes"] == {"style": "gothic"}
        assert data["candidates"][0]["evidence"]["run_id"] == str(run_id)
    changed = build(queue, selection, tmp_path / "changed")
    assert changed["counts"]["representatives"] == 0
    assert changed["exclusions"]["restricted_run"] == 1


def test_bulk_reads_finish_before_union_processing(queue, asset, tmp_path, monkeypatch):
    from colorstats.stats import snapshot

    selection = prepare(queue, asset)
    statements = []
    completed = False

    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    original = snapshot._groups

    def after_transaction(*args):
        nonlocal completed
        assert queue.engine.pool.checkedout() == 0
        completed = True
        yield from original(*args)

    monkeypatch.setattr(snapshot, "_groups", after_transaction)
    event.listen(queue.engine, "before_cursor_execute", record)
    try:
        first = build(queue, selection, tmp_path / "first")
    finally:
        event.remove(queue.engine, "before_cursor_execute", record)
    assert completed
    assert len(statements) <= 14
    second = build(queue, selection, tmp_path / "second")
    assert first["snapshot_id"] == second["snapshot_id"]
    assert first == second
