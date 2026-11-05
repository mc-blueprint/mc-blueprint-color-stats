"""ubuntu-1の隔離DB・新規保存先で直列とprovider別workerを同一予算で比較する。"""

import json
import os
import sys
from collections import Counter
from functools import partial
from pathlib import Path
from time import monotonic

import yaml
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import Session

from colorstats.collect import SearchRequest, stage
from colorstats.collect.http import MeasurementLimit
from colorstats.queue import Queue
from colorstats.queue.worker import Worker
from colorstats.schema.models import Job

ROOT = Path(__file__).resolve().parents[2]
DATABASE = Counter()


@event.listens_for(Engine, "before_cursor_execute")
def before_sql(connection, cursor, statement, parameters, context, executemany):
    context.issue91_started = monotonic()


@event.listens_for(Engine, "after_cursor_execute")
def after_sql(connection, cursor, statement, parameters, context, executemany):
    DATABASE["statements"] += 1
    DATABASE["sql_seconds"] += monotonic() - context.issue91_started


def prepare(claim):
    """通信前にprovider固有の固定予算を永続化する。各providerは単一workerが所有する。"""
    directory = Path(os.environ["ISSUE91_OUTPUT"])
    provider = claim.payload["request"]["provider"]
    path = directory / (provider + ".json")
    counts = Counter()
    events = []
    DATABASE.clear()
    started = monotonic()

    def observer(event, value=1):
        if event in ("api_request", "request"):
            key = "api" if event == "api_request" else "images"
            cap = 7 if provider == "wikimedia_commons" else (1 if key == "api" else 3)
            if counts[key] >= cap:
                raise MeasurementLimit("issue91_" + key)
            counts[key] += 1
            path.write_text(json.dumps({"counts": counts, "events": events}))
        elif event in ("bytes", "network_api_seconds", "network_media_seconds",
                       "normal_wait_seconds", "bandwidth_wait_seconds", "backoff_seconds"):
            counts[event] += value
        events.append({"event": event, "value": value})

    try:
        return stage.prepare(claim, observer=observer)
    finally:
        path.write_text(json.dumps({"counts": counts, "events": events,
                                    "database": DATABASE,
                                    "elapsed_seconds": monotonic() - started}, ensure_ascii=False))


register = stage.register


def execute(root, mode):
    directory = root / mode
    directory.mkdir()
    (directory / "raw").mkdir()
    storage = directory / "storage.yaml"
    storage.write_text(yaml.safe_dump({"storage": {"raw": [
        {"host": "ubuntu-1", "path": str(directory / "raw")},
    ]}}))
    os.environ["ISSUE91_OUTPUT"] = str(directory)
    engine = create_engine(os.environ["DATABASE_URL"])
    queue = Queue(engine)
    for provider in ("wikimedia_commons", "openverse"):
        stage.enqueue_collect(
            queue, SearchRequest(provider, "Himeji Castle", limit=1),
            policy_path=ROOT / "configs/source_policy.yaml", storage_config=storage,
            host="ubuntu-1", domain="real_building", code_version="issue91-" + mode,
            taxonomy_version="0.1.0",
        )
    before = database_stats(engine)
    started = monotonic()
    if mode == "serial":
        while claim := queue.claim(["collect"]):
            try:
                prepared = prepare(claim)
                queue.complete(claim, prepared.info, partial(register, data=prepared.data),
                               prepared.files)
            except Exception as error:
                queue.fail(claim, type(error).__name__, retryable=False)
    else:
        import multiprocessing

        context = multiprocessing.get_context("spawn")
        processes = [context.Process(target=worker, args=(provider, str(directory / "stop")))
                     for provider in ("wikimedia_commons", "openverse")]
        try:
            for process in processes:
                process.start()
            for process in processes:
                process.join(240)
                if process.exitcode != 0:
                    raise RuntimeError("並行workerが正常終了しませんでした")
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(5)
                if process.is_alive():
                    process.kill()
                    process.join()
                process.close()
    elapsed = monotonic() - started
    after = database_stats(engine)
    with Session(engine) as session:
        jobs = [{"provider": job.payload["request"]["provider"], "status": job.status,
                 "failure": job.failure_reason} for job in session.scalars(select(Job).where(
                     Job.stage == "collect", Job.payload["code_version"].astext == "issue91-" + mode
                 ))]
    report = {"wall_seconds": elapsed, "database": {k: after[k] - before[k] for k in before},
              "jobs": jobs, "providers": {
                  provider: json.loads((directory / (provider + ".json")).read_text())
                  for provider in ("wikimedia_commons", "openverse")}}
    (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"mode": mode, "wall_seconds": elapsed, "database": report["database"],
                      "jobs": jobs, "counts": {p: v["counts"]
                                               for p, v in report["providers"].items()}}),
          flush=True)
    engine.dispose()


def database_stats(engine):
    from sqlalchemy import text

    with engine.connect() as connection:
        row = connection.execute(text(
            "SELECT xact_commit, xact_rollback, blks_read, blks_hit, tup_inserted, tup_updated "
            "FROM pg_stat_database WHERE datname=current_database()"
        )).mappings().one()
        return dict(row)


def worker(provider, stop):
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        Worker(Queue(engine), {"collect": "bench.issue91.compare"}, Path(stop),
               provider=provider).run(once=True)
    finally:
        engine.dispose()


if __name__ == "__main__":
    root, mode = Path(sys.argv[1]), sys.argv[2]
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    execute(root, mode)
