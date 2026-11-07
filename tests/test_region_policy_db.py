import copy
import json
import os
from contextlib import nullcontext
from pathlib import Path

import duckdb
import numpy as np
import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from colorstats.analyze import color, region_policy, segment, segment_models, shade
from colorstats.schema.models import (
    ColorObservation,
    Job,
    ProcessingRun,
    ProcessingRunInput,
    Region,
)
from colorstats.stats.snapshot import _groups, execute, verify
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue
from tests.test_region_policy import prediction
from tests.test_region_policy import regional_payload as regional_payload
from tests.test_segment import payload as payload
from tests.test_segment_db import prep_source as prep_source

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="隔離PostgreSQL専用",
)


@pytest.fixture
def policy_source(queue, asset, regional_payload, prep_source, monkeypatch):
    monkeypatch.setattr(segment_models, "predict_regions", prediction)
    queue.enqueue("segment", asset, segment.config_hash(regional_payload), regional_payload)
    claim = queue.claim(("segment",))
    prepared = segment.prepare(claim)
    run_id = queue.complete(claim, prepared.info,
                            lambda session, run: segment.register(session, run, prepared.data),
                            prepared.files)
    with Session(queue.engine) as session:
        source = session.get(ProcessingRun, run_id)
        policy = color.region_policy_input(session, asset, run_id)
        assert policy == region_policy.reference(source)
        raw = list(session.scalars(select(Region).where(Region.processing_run_id == run_id)))
        assert len(raw) == len(regional_payload["prompts"])
        assert np.all(np.array(Image.open(raw[0].mask_path)) == 255)
        refs = color.region_inputs(session, asset, run_id)
        assert session.get(ProcessingRunInput, (run_id, prep_source)) is not None
        assert source.parameters["region_policy"]["semantic"]["path"] != policy["semantic"]["path"]
    return {"input_path": regional_payload["input_path"],
            "input_sha256": regional_payload["input_sha256"],
            "input_run_id": str(prep_source), "region_run_id": str(run_id), "regions": refs,
            "region_policy": policy, "taxonomy_version": "0.1.0", "license_class": "open",
            "output_path": str(Path(regional_payload["output_path"]).with_name("color.json"))}


@pytest.mark.parametrize("stage", ["color", "shade"])
def test_segment_to_color_shade_snapshot_immutable_provenance(queue, asset, policy_source, stage):
    handler = color if stage == "color" else shade
    payload = {**policy_source, **({"method": "none"} if stage == "shade" else {})}
    queue.enqueue(stage, asset, handler.config_hash(payload), payload)
    claim = queue.claim((stage,))
    prepared = handler.prepare(claim)
    run_id = queue.complete(claim, prepared.info,
                            lambda session, run: handler.register(session, run, prepared.data),
                            prepared.files)
    with Session(queue.engine) as session:
        run = session.get(ProcessingRun, run_id)
        source = session.get(ProcessingRun, policy_source["region_run_id"])
        assert session.scalar(select(func.count()).select_from(ColorObservation)) == 0
        assert session.scalar(select(func.count()).select_from(Region)) == len(payload["regions"])
        assert session.get(ProcessingRunInput, (run_id, source.id)) is not None
        assert run.license_class == "noncommercial"
        assert Path(run.output_paths[payload["output_path"]]).is_file()
        assert prepared.data["roles"]["real_building/wall"]["area"] == 43
        if stage == "color":
            group_rows = list(_groups(
                {"id": asset, "domain": "real_building"},
                {"color": run.id, "segment": source.id}, [],
                {"parameters": run.parameters, "config_hash": run.config_hash},
                {"id": source.id, "parameters": source.parameters,
                 "output_paths": source.output_paths}, {},
            ))
            wall = next(row for row in group_rows if row["role"] == "real_building/wall")
            assert wall["data"]["area"] == 43
            assert not wall["quality_eligible"]
    if stage == "color":
        from tests.test_stats_snapshot_db import QUALITY

        quality = copy.deepcopy(QUALITY)
        quality["segment"] = {"method": region_policy.METHOD}
        selection = {"taxonomy_version": "0.1.0", "assets": [{
            "asset_id": str(asset), "prep_run_id": payload["input_run_id"],
            "segment_run_id": payload["region_run_id"], "color_run_id": str(run_id),
        }]}
        output = Path(payload["output_path"]).parent / "snapshot"
        result = execute(queue.engine, selection, output, quality=quality, code_version="test")
        assert verify(output, result["snapshot_id"]) == result
        with duckdb.connect() as db:
            rows = db.execute("SELECT role, quality_eligible FROM read_parquet(?)",
                              [str(output / "groups.parquet")]).fetchall()
        assert ("real_building/wall", False) in rows


@pytest.mark.parametrize("change", ["missing", "run", "model", "old_observations"])
def test_register_rejects_raw_fallback_and_replaced_policy(queue, asset, policy_source, change):
    payload = copy.deepcopy(policy_source)
    if change == "missing":
        payload.pop("region_policy")
    elif change == "run":
        payload["region_policy"]["run_id"] = "other"
    elif change == "model":
        payload["region_policy"]["model"]["revision"] = "other"
    if change == "run":
        with pytest.raises(ValueError, match="run"):
            color.config_hash(payload)
        return
    queue.enqueue("color", asset, color.config_hash(payload), payload)
    claim = queue.claim(("color",))
    prepared = color.prepare(claim)
    if change == "old_observations":
        prepared.data["regions"] = [{"region_id": payload["regions"][0]["region_id"]}]
    with pytest.raises(ValueError, match="policy|旧観測"):
        queue.complete(claim, prepared.info,
                       lambda session, run: color.register(session, run, prepared.data),
                       prepared.files)
    with Session(queue.engine) as session:
        assert session.scalar(select(func.count()).select_from(ColorObservation)) == 0


@pytest.mark.skipif(os.name != "posix", reason="runnerのflockはLinux専用")
def test_runner_oom_fails_once_and_leaves_stop_file(
    queue, asset, regional_payload, prep_source, tmp_path, monkeypatch,
):
    from ops.deploy import m3_analysis

    root = tmp_path / "batch-oom"
    root.mkdir()
    row = {"asset_id": str(asset), "prep_status": "succeeded", "license_class": "open",
           "taxonomy_version": "0.1.0", "input_run_id": str(prep_source),
           "input_path": regional_payload["input_path"],
           "input_sha256": regional_payload["input_sha256"]}
    manifest = {"assets": [row], "settings": {
        "segment": {"method": region_policy.METHOD, "prompts": regional_payload["prompts"]},
        "shade": {"method": "none"},
    }, "implementation": m3_analysis.implementation()}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(m3_analysis, "Sampler", lambda path: nullcontext())
    seen = []

    def fail(worker, claim):
        seen.append(claim.stage)
        worker.queue.fail(claim, region_policy.OOM_REASON, retryable=False)

    monkeypatch.setattr(m3_analysis.Worker, "_run_claim", fail)
    m3_analysis.run_batch(queue.engine, root, manifest, tmp_path, None)
    assert (root / "stop").exists() and seen == ["segment"]
    with Session(queue.engine) as session:
        job = session.scalars(select(Job).where(Job.stage == "segment")).one()
        assert job.status == "failed" and job.attempts == 1
