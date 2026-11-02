import os
from dataclasses import replace

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from colorstats.analyze.shade import config_hash
from colorstats.queue.worker import Worker
from colorstats.schema.models import ColorObservation, Job, ProcessingRun, ProcessingRunInput
from tests.test_part_color_db import part_payload
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="一時PostgreSQL専用",
)


@pytest.mark.parametrize("kind", ["model", "human"])
@pytest.mark.parametrize("method", ["none", "gray-world"])
def test_worker_material_and_provenance(queue, asset, tmp_path, kind, method):
    payload = part_payload(queue, asset, tmp_path, kind)
    with Image.open(payload["input_path"]) as image:
        pixels = (np.asarray(image) * 0.7 + 30).astype(np.uint8)
    Image.fromarray(pixels).save(payload["input_path"])
    payload["method"] = method
    job_id = queue.enqueue("shade", asset, config_hash(payload), payload)
    Worker(queue, {"shade": "colorstats.analyze.shade"}, tmp_path / "stop").run(once=True)
    with Session(queue.engine) as session:
        job = session.get(Job, job_id)
        assert job.status == "succeeded", job.failure_reason
        run = session.get(ProcessingRun, job.run_id)
        rows = session.scalars(select(ColorObservation).where(
            ColorObservation.processing_run_id == run.id,
        )).all()
        assert len(rows) == 2
        assert all(row.region_id is not None and row.material_oklab for row in rows)
        assert all(row.material_confidence == 1 for row in rows)
        assert run.license_class == "academic_only"
        assert session.get(ProcessingRunInput, (run.id, payload["region_run_id"])) is not None
        if method == "none":
            assert all(row.observed_oklab == row.material_oklab for row in rows)


@pytest.mark.parametrize("fault", ["raw", "region", "taxonomy", "prep"])
def test_register_rejects_changed_input(queue, asset, tmp_path, fault):
    from colorstats.analyze.shade import prepare, register

    payload = part_payload(queue, asset, tmp_path, "model")
    payload["method"] = "none"
    queue.enqueue("shade", asset, config_hash(payload), payload)
    claim = queue.claim(("shade",))
    prepared = prepare(claim)
    info = prepared.info
    if fault == "raw":
        from colorstats.schema.models import Asset

        with Session(queue.engine) as session, session.begin():
            session.get(Asset, asset).storage_path = "another.png"
    elif fault == "region":
        prepared.info.parameters["payload"]["regions"][0]["mask_path"] = "another.png"
    elif fault == "taxonomy":
        info = replace(info, taxonomy_version="wrong")
    else:
        prepared.data["input_run_id"] = str(asset)
    with pytest.raises(ValueError):
        queue.complete(claim, info, lambda s, r: register(s, r, prepared.data), prepared.files)
