import copy
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from colorstats.queue import LeaseLost
from colorstats.queue.worker import Worker
from colorstats.schema.models import Job, ProcessingRun, ProcessingRunInput, RuleStat
from colorstats.stats import aggregate as module
from colorstats.stats.aggregate_cli import main
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import expire
from tests.test_queue import queue as queue
from tests.test_stats_aggregate import settings as settings
from tests.test_stats_aggregate import snapshot
from tests.test_stats_snapshot_db import build, prepare

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="隔離PostgreSQL16専用",
)


def enqueue(queue, tmp_path, settings):
    run_id = uuid4()
    source = {"id": str(run_id), "stage": "color", "data": {
        "config_hash": "a" * 64, "code_version": "fixture", "input_run_ids": [],
        "parameters": {}, "weights_hash": None, "model_name": None, "license_class": "open",
    }}
    with Session(queue.engine) as session, session.begin():
        session.add(ProcessingRun(
            id=run_id, stage="color", license_class="open", config_hash="a" * 64,
            code_version="fixture", node="test", taxonomy_version="0.1.0",
            parameters={}, started_at=datetime.now(UTC), finished_at=datetime.now(UTC),
        ))
    root = tmp_path / "snapshot"
    identifier = snapshot(root, 30, input_runs=[source])
    payload = {"snapshot": str(root), "snapshot_id": identifier,
               "settings": settings, "output_path": str(tmp_path / "aggregate.json")}
    job = queue.enqueue("aggregate", None, module.config_hash(payload), payload)
    return job, payload, run_id


def counts(queue):
    with Session(queue.engine) as session:
        return [session.scalar(select(func.count()).select_from(model))
                for model in (RuleStat, ProcessingRun, ProcessingRunInput)]


def test_worker_commit_idempotency_and_cli(queue, tmp_path, settings, monkeypatch):
    job_id, payload, source = enqueue(queue, tmp_path, settings)
    monkeypatch.setattr("colorstats.stats.aggregate_cli.load_settings", lambda *args: settings)
    monkeypatch.setenv("DATABASE_URL", queue.engine.url.render_as_string(hide_password=False))
    monkeypatch.setattr("sys.argv", [
        "aggregate", "--snapshot", payload["snapshot"], "--snapshot-id", payload["snapshot_id"],
        "--output", payload["output_path"],
    ])
    assert main() == 0
    Worker(queue, {"aggregate": "colorstats.stats.aggregate"}, tmp_path / "stop").run(once=True)
    with Session(queue.engine) as session:
        job = session.get(Job, job_id)
        assert job.status == "succeeded"
        run = session.get(ProcessingRun, job.run_id)
        assert run.output_paths and run.finished_at
        assert session.get(ProcessingRunInput, (run.id, source))
        assert session.scalar(select(func.count()).select_from(RuleStat)) > 0
        assert session.scalar(select(func.count()).select_from(RuleStat).where(
            RuleStat.confidence_interval.is_not(None),
        )) == 0
    before = counts(queue)
    assert queue.enqueue("aggregate", None, module.config_hash(payload), payload) == job_id
    assert main() == 0
    assert queue.claim(["aggregate"]) is None
    assert counts(queue) == before


def test_lease_loss_publishes_nothing_and_retry(queue, tmp_path, settings):
    _, _, _ = enqueue(queue, tmp_path, settings)
    first = queue.claim(["aggregate"])
    result = module.prepare(first)
    expire(queue, first)
    second = queue.claim(["aggregate"])
    before = counts(queue)
    with pytest.raises(LeaseLost):
        queue.complete(first, result.info, lambda s, r: module.register(s, r, result.data))
    assert counts(queue) == before
    run_id = queue.complete(second, result.info, lambda s, r: module.register(s, r, result.data))
    assert queue.complete(second, result.info, lambda s, r: pytest.fail("二重登録")) == run_id
    assert counts(queue)[0] == len(result.data["rows"])


def test_database_error_rolls_back_all_results(queue, tmp_path, settings):
    enqueue(queue, tmp_path, settings)
    claim = queue.claim(["aggregate"])
    result = module.prepare(claim)
    before = counts(queue)

    def fail(session, run):
        module.register(session, run, result.data)
        session.flush()
        session.execute(text("SELECT 1 / 0"))

    with pytest.raises(DBAPIError):
        queue.complete(claim, result.info, fail)
    assert counts(queue) == before
    with Session(queue.engine) as session:
        assert session.get(Job, claim.id).status == "running"
    queue.complete(claim, result.info, lambda s, r: module.register(s, r, result.data))
    assert counts(queue)[0] == len(result.data["rows"])


def test_input_run_mismatch_rolls_back(queue, tmp_path, settings):
    enqueue(queue, tmp_path, settings)
    claim = queue.claim(["aggregate"])
    result = module.prepare(claim)
    data = copy.deepcopy(result.data)
    data["input_runs"][0]["data"]["config_hash"] = "b" * 64
    before = counts(queue)
    with pytest.raises(ValueError, match="由来"):
        queue.complete(claim, result.info, lambda s, r: module.register(s, r, data))
    assert counts(queue) == before


def test_real_snapshot_contract_with_excluded_inputs(queue, asset, tmp_path, settings):
    selection = prepare(queue, asset)
    root = tmp_path / "snapshot"
    manifest = build(queue, selection, root)
    payload = {"snapshot": str(root), "snapshot_id": manifest["snapshot_id"], "settings": settings,
               "output_path": str(tmp_path / "aggregate.json")}
    queue.enqueue("aggregate", None, module.config_hash(payload), payload)
    claim = queue.claim(["aggregate"])
    result = module.prepare(claim)
    # 権利除外・SHA重複のrunを、新しい主統計の解析入力へ戻さない。
    assert len(result.data["input_runs"]) == 6
    run_id = queue.complete(claim, result.info, lambda s, r: module.register(s, r, result.data))
    with Session(queue.engine) as session:
        rows = session.scalars(select(RuleStat).where(RuleStat.processing_run_id == run_id)).all()
        door = next(r for r in rows if r.target_parts == ["door"] and len(r.conditions) == 1)
        assert door.subject_count == 0
        assert door.quality["unknown_images"] == 2
        assert door.quality["status"] == "unsupported"
