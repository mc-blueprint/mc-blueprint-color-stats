import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from colorstats.analyze.color import config_hash, prepare, region_inputs, register
from colorstats.queue import RunInfo
from colorstats.queue.worker import Worker
from colorstats.schema.models import (
    Asset,
    ColorObservation,
    Job,
    ProcessingRun,
    ProcessingRunInput,
    Region,
    Relation,
)
from tests.test_color import scene
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="一時PostgreSQL専用",
)


def part_payload(queue, asset, tmp_path, kind, run_index=0, image_path=None):
    image = image_path or tmp_path / "scene.png"
    scene().save(image)
    with Session(queue.engine) as session, session.begin():
        target = session.get(Asset, asset)
        target.storage_path = str(image)
        target.width = target.height = 80
    if kind == "model":
        queue.enqueue("segment", asset, f"{run_index:064x}", {})
        claim = queue.claim(("segment",))
        info = RunInfo("academic_only", "test", "0.1.0", "test", {
            "payload": {"input_path": str(image)}, "metrics": {"width": 20, "height": 20},
        })
        run_id = queue.complete(claim, info, lambda s, r: None)
    else:
        with Session(queue.engine) as session, session.begin():
            run = ProcessingRun(
                stage="human_annotation", license_class="academic_only", config_hash="e" * 64,
                parameters={}, code_version="test", taxonomy_version="0.1.0", node="test",
                started_at=datetime.now(UTC), finished_at=datetime.now(UTC),
                output_paths={"masks": str(tmp_path)},
            )
            session.add(run)
            session.flush()
            run_id = run.id
    with Session(queue.engine) as session, session.begin():
        run = session.get(ProcessingRun, run_id)
        outputs = dict(run.output_paths)
        for index, (start, stop) in enumerate(((0, 15), (15, 20))):
            if kind == "model":
                path = tmp_path / f"part-{index}.png"
                mask = np.zeros((20, 20), dtype=np.uint8)
                mask[:, start:stop] = 255
                Image.fromarray(mask).save(path)
                outputs[str(path)] = str(path)
                reference = str(path)
            else:
                path = tmp_path / f"part-{index}.json"
                path.write_text(json.dumps({"format": "polygon-pixels-v1", "points": [
                    [start * 4, 0], [(stop - 1) * 4, 0],
                    [(stop - 1) * 4, 76], [start * 4, 76],
                ]}))
                reference = path.name
            session.add(Region(
                id=UUID(int=run_index * 2 + index + 1), asset_id=asset, processing_run_id=run.id,
                taxonomy_version="0.1.0", label=("wall_main", "roof_surface")[index],
                instance_id=str(index), mask_path=reference, bbox=[start, 0, stop, 20],
                label_source=kind, confidence=1, area_ratio=(stop - start) / 20,
            ))
        run.output_paths = outputs
    with Session(queue.engine) as session:
        rows = region_inputs(session, asset, run_id)
    return {
        "input_path": str(image), "output_path": str(tmp_path / "color.json"),
        "license_class": "open", "taxonomy_version": "0.1.0",
        "region_run_id": str(run_id), "regions": rows,
    }


@pytest.mark.parametrize("kind", ["model", "human"])
def test_part_worker_baseline_relations_and_provenance(queue, asset, tmp_path, kind):
    payload = part_payload(queue, asset, tmp_path, kind)
    job_id = queue.enqueue("color", asset, config_hash(payload), payload)
    Worker(queue, {"color": "colorstats.analyze.color"}, tmp_path / "stop").run(once=True)
    with Session(queue.engine) as session:
        job = session.get(Job, job_id)
        assert job.status == "succeeded", job.failure_reason
        run = session.get(ProcessingRun, job.run_id)
        rows = session.scalars(select(ColorObservation).where(
            ColorObservation.processing_run_id == run.id,
        )).all()
        assert len(rows) == 4
        assert sum(row.asset_id == asset and row.region_id is None for row in rows) == 2
        assert sum(row.region_id is not None and row.asset_id is None for row in rows) == 2
        relation = session.scalar(select(Relation).where(Relation.processing_run_id == run.id))
        assert relation.region_a == UUID(int=1) and relation.region_b == UUID(int=2)
        assert relation.type == "co_occurs" and relation.area_ratio == pytest.approx(1 / 3)
        assert relation.delta_e_ok > 0
        assert run.license_class == "academic_only"
        assert session.get(ProcessingRunInput, (run.id, payload["region_run_id"])) is not None
        published = Path(run.output_paths[payload["output_path"]])
        data = json.loads(published.read_text(encoding="utf-8"))
        assert data["relations"][0]["delta_l"] == relation.delta_l
        assert data["region_run_id"] == payload["region_run_id"]
    assert queue.enqueue("color", asset, config_hash(payload), payload) == job_id
    assert queue.claim(("color",)) is None


@pytest.mark.parametrize("selected", [0, 1, 2])
def test_explicit_run_selects_only_its_regions_with_model_and_human_runs(
    queue, asset, tmp_path, selected,
):
    payloads = []
    for index, kind in enumerate(("model", "model", "human")):
        directory = tmp_path / str(index)
        directory.mkdir()
        payloads.append(part_payload(
            queue, asset, directory, kind, run_index=index, image_path=tmp_path / "scene.png",
        ))
    payload = payloads[selected]
    expected = {UUID(int=selected * 2 + offset) for offset in (1, 2)}
    with Session(queue.engine) as session:
        rows = region_inputs(session, asset, payload["region_run_id"])
        assert rows == payload["regions"]
        assert {UUID(row["region_id"]) for row in rows} == expected
    job_id = queue.enqueue("color", asset, config_hash(payload), payload)
    Worker(queue, {"color": "colorstats.analyze.color"}, tmp_path / "stop").run(once=True)
    with Session(queue.engine) as session:
        job = session.get(Job, job_id)
        assert job.status == "succeeded", job.failure_reason
        observations = session.scalars(select(ColorObservation).where(
            ColorObservation.processing_run_id == job.run_id,
            ColorObservation.region_id.is_not(None),
        )).all()
        assert len(observations) == 2
        assert {row.region_id for row in observations} == expected
        relation = session.scalars(select(Relation).where(
            Relation.processing_run_id == job.run_id,
        )).one()
        assert {relation.region_a, relation.region_b} == expected
        assert set(session.scalars(select(ProcessingRunInput.input_run_id).where(
            ProcessingRunInput.run_id == job.run_id,
        ))) == {UUID(payload["region_run_id"])}


@pytest.mark.parametrize("fault", ["path", "region", "image", "prep", "taxonomy", "unfinished"])
def test_invalid_provenance_rolls_back_all_results(queue, asset, tmp_path, fault):
    payload = part_payload(queue, asset, tmp_path, "model")
    if fault == "path":
        copy = tmp_path / "copied.png"
        copy.write_bytes(Path(payload["regions"][0]["mask_path"]).read_bytes())
        payload["regions"][0]["mask_path"] = str(copy)
    elif fault == "region":
        payload["regions"][0]["region_id"] = str(UUID(int=0))
    elif fault == "image":
        copy = tmp_path / "copied.png"
        scene().save(copy)
        payload["input_path"] = str(copy)
    elif fault == "prep":
        payload["input_run_id"] = str(uuid4())
    else:
        with Session(queue.engine) as session, session.begin():
            run = session.get(ProcessingRun, payload["region_run_id"])
            if fault == "taxonomy":
                run.taxonomy_version = "wrong"
            else:
                run.finished_at = None
    job_id = queue.enqueue("color", asset, config_hash(payload), payload)
    claim = queue.claim(("color",))
    result = prepare(claim)
    with pytest.raises(ValueError):
        queue.complete(claim, result.info, lambda s, r: register(s, r, result.data), result.files)
    with Session(queue.engine) as session:
        assert session.get(Job, job_id).run_id is None
        assert session.scalar(select(func.count()).select_from(ColorObservation)) == 0
        assert session.scalar(select(func.count()).select_from(Relation)) == 0
