import os
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from colorstats.analyze import color, region_policy, segment, segment_models, shade, visible_wall
from colorstats.schema.models import ProcessingRun, ProcessingRunInput, Region
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue
from tests.test_region_policy import regional_payload as regional_payload
from tests.test_segment import payload as payload
from tests.test_segment_db import prep_source as prep_source
from tests.test_visible_wall import visible_prediction

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="隔離DB専用")


@pytest.mark.parametrize("stage", ["color", "shade"])
def test_visible_wall_keeps_same_segment_run_for_downstream(
    queue, asset, regional_payload, prep_source, monkeypatch, stage,
):
    regional_payload["method"] = visible_wall.METHOD
    monkeypatch.setattr(segment_models, "predict_regions", visible_prediction)
    queue.enqueue("segment", asset, segment.config_hash(regional_payload), regional_payload)
    claim = queue.claim(("segment",))
    prepared = segment.prepare(claim)
    source_id = queue.complete(claim, prepared.info,
                              lambda s, run: segment.register(s, run, prepared.data),
                              prepared.files)
    with Session(queue.engine) as session:
        source = session.get(ProcessingRun, source_id)
        policy = region_policy.reference(source)
        assert policy["version"] == visible_wall.VERSION
        assert len(policy["wall_candidates"]) == 1
        assert all(not label.startswith("exclude/") for label in session.scalars(
            select(Region.label).where(Region.processing_run_id == source_id)))
        refs = color.region_inputs(session, asset, source_id)
    payload = {"input_path": regional_payload["input_path"],
               "input_sha256": regional_payload["input_sha256"],
               "input_run_id": str(prep_source), "region_run_id": str(source_id),
               "region_policy": policy, "regions": refs, "taxonomy_version": "0.1.0",
               "license_class": "open", "output_path": str(Path(regional_payload[
                   "output_path"]).with_name(f"visible-{stage}.json"))}
    handler = color if stage == "color" else shade
    if stage == "shade":
        payload["method"] = "none"
    queue.enqueue(stage, asset, handler.config_hash(payload), payload)
    claim = queue.claim((stage,))
    prepared = handler.prepare(claim)
    target_id = queue.complete(claim, prepared.info,
                              lambda s, run: handler.register(s, run, prepared.data),
                              prepared.files)
    assert prepared.data["roles"][visible_wall.WALL]["area"] == 42
    with Session(queue.engine) as session:
        assert session.get(ProcessingRunInput, (target_id, source_id)) is not None
        saved = session.get(ProcessingRun, target_id).parameters["payload"]["region_policy"]
        assert saved == policy
