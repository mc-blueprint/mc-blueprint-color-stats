import json
import os
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from colorstats.analyze.color import prepare, register
from colorstats.queue.worker import Worker
from colorstats.schema.models import ColorObservation, Job, ProcessingRun, ProcessingRunInput
from tests.test_color import scene
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="CIのPostgreSQL専用"
)


def test_prep_to_color_worker_and_provenance(queue, asset, tmp_path):
    source = tmp_path / "source.png"
    derived = tmp_path / "resized.jpg"
    target = tmp_path / "colors.json"
    scene().resize((400, 400)).save(source)
    payload = {
        "input_path": str(source), "derived_path": str(derived),
        "license_class": "open", "taxonomy_version": "0.1.0",
    }
    prep_id = queue.enqueue("prep", asset, "a" * 64, payload)
    Worker(queue, {"prep": "colorstats.analyze.prep"}, tmp_path / "stop").run(once=True)
    with Session(queue.engine) as session:
        prep_job = session.get(Job, prep_id)
        assert prep_job.status == "succeeded"
        prep_run = session.get(ProcessingRun, prep_job.run_id)
        input_path = prep_run.output_paths[str(derived)]
        input_run_id = str(prep_run.id)
    payload = {
        "input_path": input_path, "input_run_id": input_run_id,
        "output_path": str(target), "license_class": "open", "taxonomy_version": "0.1.0",
    }
    job_id = queue.enqueue("color", asset, "b" * 64, payload)
    Worker(queue, {"color": "colorstats.analyze.color"}, tmp_path / "stop").run(once=True)
    with Session(queue.engine) as session:
        job = session.get(Job, job_id)
        assert job.status == "succeeded", job.failure_reason
        run = session.get(ProcessingRun, job.run_id)
        published = Path(run.output_paths[str(target)])
        data = json.loads(published.read_text(encoding="utf-8"))
        rows = session.scalars(
            select(ColorObservation).where(ColorObservation.processing_run_id == run.id)
        ).all()
        assert len(rows) == len(data["observations"])
        assert sum(row.area_ratio for row in rows) == pytest.approx(1)
        assert all(row.asset_id == asset and row.region_id is None for row in rows)
        assert all(row.material_oklab is None and row.material_confidence is None for row in rows)
        assert sorted(row.area_ratio for row in rows)[-1] == pytest.approx(0.75, abs=0.02)
        assert session.get(ProcessingRunInput, (run.id, input_run_id)) is not None
        assert run.parameters["seed"] == 0
        assert not target.exists()
    assert queue.enqueue("color", asset, "b" * 64, payload) == job_id
    assert queue.claim(("color",)) is None


def test_repeated_complete_does_not_duplicate_observations(queue, asset, tmp_path):
    source = tmp_path / "scene.png"
    scene().save(source)
    queue.enqueue("color", asset, "c" * 64, {
        "input_path": str(source), "output_path": str(tmp_path / "colors.json"),
        "license_class": "open", "taxonomy_version": "0.1.0",
    })
    claim = queue.claim(("color",))
    result = prepare(claim)
    def callback(session, run):
        register(session, run, result.data)

    first = queue.complete(claim, result.info, callback, result.files)
    assert queue.complete(claim, result.info, callback, result.files) == first
    with Session(queue.engine) as session:
        assert session.scalar(select(func.count()).select_from(ColorObservation)) == 2


def test_no_valid_pixels_does_not_register_success(queue, asset, tmp_path):
    source = tmp_path / "white.png"
    Image.new("RGB", (10, 10), "white").save(source)
    job_id = queue.enqueue("color", asset, "d" * 64, {
        "input_path": str(source), "output_path": str(tmp_path / "colors.json"),
        "license_class": "open", "taxonomy_version": "0.1.0",
    })
    Worker(queue, {"color": "colorstats.analyze.color"}, tmp_path / "stop").run(once=True)
    with Session(queue.engine) as session:
        job = session.get(Job, job_id)
        assert job.status == "pending"
        assert "有効画素" in job.failure_reason
        assert job.run_id is None
        assert session.scalar(select(func.count()).select_from(ColorObservation)) == 0
