import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from colorstats.queue.worker import Worker
from colorstats.schema.models import Asset, Job, ProcessingRun, ProcessingRunInput
from colorstats.stats import aggregate
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue
from tests.test_stats_aggregate import settings as settings
from tests.test_stats_snapshot_db import build, prepare

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="隔離PostgreSQL専用",
)


def test_attribute_rights_do_not_exclude_open_images_or_hide_image_rights(
    queue, asset, tmp_path, settings,
):
    selection = prepare(queue, asset)
    before = build(queue, selection, tmp_path / "before")
    rid = uuid4()
    with Session(queue.engine) as session, session.begin():
        session.add(ProcessingRun(
            id=rid, stage="subject", license_class="restricted", config_hash="f" * 64,
            parameters={"method": "saved-evidence-v1"}, taxonomy_version="0.1.0",
            code_version="test", node="test", started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        ))
        row = session.get(Asset, UUID(int=1))
        row.quality = dict(row.quality) | {"scene_inference": {"run_id": str(rid)}}
    root = tmp_path / "after"
    after = build(queue, selection, root)
    for key in ("rights_eligible", "analysis_eligible", "representatives",
                "observations_eligible", "relations_eligible"):
        assert before["counts"][key] == after["counts"][key]
    assert "restricted_weights" in after["exclusions"]
    assert "license_conditions" in after["exclusions"]
    payload = {"snapshot": str(root), "snapshot_id": after["snapshot_id"],
               "settings": settings, "output_path": str(tmp_path / "aggregate.json")}
    job_id = queue.enqueue("aggregate", None, aggregate.config_hash(payload), payload)
    Worker(queue, {"aggregate": "colorstats.stats.aggregate"}, tmp_path / "stop").run(once=True)
    with Session(queue.engine) as session:
        job = session.get(Job, job_id)
        assert job.status == "succeeded"
        run = session.get(ProcessingRun, job.run_id)
        assert run.license_class == "open"
        assert str(rid) in run.parameters["subject_attribute_run_ids"]
        assert session.get(ProcessingRunInput, (run.id, rid))
