"""#114バッチ1の有限計画・監視・新規cohortのprep。既存pilotは起動しない。"""

import argparse
import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import UUID

import yaml
from ops.deploy.pilot import config_hash
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from colorstats.collect.bias import plan
from colorstats.collect.measurement import report
from colorstats.collect.targets import load_targets
from colorstats.queue import Queue
from colorstats.queue.worker import Worker
from colorstats.schema.models import Asset, CollectionLimit, Job

ROOT = Path(__file__).resolve().parents[2]
BUDGET = {"id": "issue114-batch1", "images": 3000, "api_requests": 10000,
          "bytes": 15000000000, "consecutive_errors": 3}


def check_analysis(result, assets, *, limit=None):
    """smokeまたは全量のshade・colorまでの完了を検査する。"""
    expected = assets if limit is None else min(assets, limit)
    if result["violations"] or result["unclosed_attempts"]:
        raise ValueError("GPU解析reportの由来または試行が未確定です")
    if (result["completed_assets"] != expected
            or result["pending_assets"] != assets - expected):
        raise ValueError("shade・colorを含むGPU解析が未完了です")
    successful = {stage: {job["asset_id"] for job in result.get("jobs", [])
                          if job["stage"] == stage and job["status"] == "succeeded"
                          and job.get("run_id")}
                  for stage in ("segment", "shade", "color")}
    if (len(successful["color"]) != expected
            or successful["shade"] != successful["color"]
            or not successful["color"] <= successful["segment"]
            or "jobs" not in result):
        raise ValueError("同一画像のsegment・shade・color三段階が完了していません")


def save(path, data, *, exclusive=False):
    with path.open("x" if exclusive else "w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, default=str)
        stream.write("\n")


def baseline(engine, root):
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        assets = list(connection.execute(text(
            "SELECT id::text,md5(row_to_json(a)::text) FROM asset a ORDER BY id"
        )))
        save(root / "baseline-assets.json", dict(assets), exclusive=True)
        save(root / "baseline-runs.json", dict(connection.execute(text(
            "SELECT id::text,md5(row_to_json(r)::text) FROM processing_run r ORDER BY id"
        )).all()), exclusive=True)


def collect(engine, root, version, *, resume=False):
    identifiers = []
    if resume:
        if json.loads((root / "budget.json").read_text()) != BUDGET:
            raise ValueError("保存済み予算が一致しません")
        json.loads((root / "baseline-assets.json").read_text())
        identifiers = [UUID(value) for value in json.loads(
            (root / "collect-jobs.json").read_text()
        )]
    else:
        baseline(engine, root)
        save(root / "budget.json", BUDGET, exclusive=True)
    config = load_targets(ROOT / "configs/collection_targets.yaml", ROOT / "taxonomy")
    policy = yaml.safe_load((ROOT / "configs/source_policy.yaml").read_text())
    for host in ("upload.wikimedia.org", "thumb.wikimedia.org"):
        policy["sources"]["wikimedia_commons"]["hosts"][host][
            "media_bytes_per_10_seconds"
        ] = 25000000
    policy_path = root / "source_policy.yaml"
    if resume:
        if yaml.safe_load(policy_path.read_text()) != policy:
            raise ValueError("保存済みpolicyが一致しません")
        archive = root / ("attempt-" + str(time.time_ns()))
        archive.mkdir()
        for name in ("collect.stop", "collection.json", "new-assets.json", "collect-jobs.json"):
            (root / name).rename(archive / name)
    else:
        policy_path.write_text(yaml.safe_dump(policy, allow_unicode=True, sort_keys=False))
    stop = root / "collect.stop"
    command = [sys.executable, "-m", "colorstats.queue", "--handler",
               "collect=colorstats.collect.bias", "--provider", "wikimedia_commons",
               "--stop-file", str(stop), "--storage-path", "collect=/srv/colorstats/raw-orico",
               "--storage-path", "collect=/srv/colorstats/raw-suneast"]
    worker = subprocess.Popen(command)
    queue = Queue(engine)
    reason = "planned_search_exhausted"
    try:
        for priority in (1, 2, 3):
            target = copy.deepcopy(config)
            target["strata"] = [s for s in target["strata"] if s["priority"] == priority]
            target["measurement"] = {
                "id": f"issue114-batch1-p{priority}", "api_requests_per_stratum": 10000,
                "http_requests_per_stratum": 50000, "first_page_only": False, "budget": BUDGET,
            }
            for seed in range(20):
                identifiers.extend(plan(
                    queue, target, policy_path=policy_path,
                    storage_config=ROOT / "configs/storage.yaml",
                    host="ubuntu-1", code_version=version, seed=seed,
                ))
                while True:
                    with Session(engine) as session:
                        ledger = session.get(CollectionLimit, "batch:" + BUDGET["id"])
                        state = dict(ledger.state) if ledger else {}
                        jobs = session.scalars(select(Job).where(Job.id.in_(identifiers))).all()
                        active = [job for job in jobs if job.status in ("pending", "running")]
                        running = any(job.status == "running" for job in active)
                    save(root / "status.json", {"priority": priority, "seed": seed,
                                               "budget": state, "active_jobs": len(active)})
                    reached = next((key for key in ("images", "api_requests", "bytes")
                                    if state.get(key, 0) >= BUDGET[key]), None)
                    if state.get("stop_reason") or (reached and not running):
                        reason = state.get("stop_reason") or "batch_" + reached + "_limit"
                        return
                    if worker.poll() is not None:
                        if worker.returncode == 0 and stop.exists():
                            reason = "operator_stop"
                            return
                        raise RuntimeError("provider workerが予期せず終了しました")
                    if not active:
                        break
                    time.sleep(5)
    except BaseException as error:
        reason = "failed:" + type(error).__name__
        raise
    finally:
        stop.touch(exist_ok=True)
        try:
            worker.wait(timeout=150)
        except subprocess.TimeoutExpired:
            worker.terminate()
            worker.wait(timeout=150)
            raise RuntimeError("provider workerの正常終了を確認できません") from None
        with Session(engine) as session:
            trials = {str(p): report(session, f"issue114-batch1-p{p}") for p in (1, 2, 3)}
            old = set(json.loads((root / "baseline-assets.json").read_text()))
            new = [str(aid) for aid in session.scalars(select(Asset.id)) if str(aid) not in old]
        save(root / "collection.json", {"reason": reason, "worker_exit": worker.returncode,
                                        "measurements": trials}, exclusive=True)
        save(root / "new-assets.json", sorted(new), exclusive=True)
        save(root / "collect-jobs.json", [str(value) for value in identifiers], exclusive=True)
        print(json.dumps({"reason": reason, "new_assets": len(new),
                          "worker_exit": worker.returncode}), flush=True)


def prepare(engine, root, version):
    identifiers = [UUID(value) for value in json.loads((root / "new-assets.json").read_text())]
    queue = Queue(engine)
    jobs = []
    with Session(engine) as session:
        for asset in session.scalars(select(Asset).where(Asset.id.in_(identifiers))):
            payload = {"input_path": asset.storage_path,
                       "derived_path": str(root / "prep" / str(asset.id) / "prep.jpg"),
                       "license_class": asset.license_class,
                       "taxonomy_version": asset.taxonomy_version, "preserve_other_assets": True}
            jobs.append(queue.enqueue(
                "prep", asset.id, config_hash("prep", payload, version), payload,
            ))
    worker = Worker(queue, {"prep": "colorstats.analyze.prep"}, root / "prep.stop")
    try:
        while claim := queue.claim(["prep"], job_ids=jobs):
            worker._run_claim(claim)
    finally:
        worker._stop_prepare()
    with Session(engine) as session:
        result = [{"asset_id": str(job.asset_id), "status": job.status,
                   "run_id": str(job.run_id) if job.run_id else None, "reason": job.failure_reason}
                  for job in session.scalars(select(Job).where(Job.id.in_(jobs)))]
    save(root / "prep-report.json", result, exclusive=True)
    print(json.dumps({"prep_jobs": len(result), "success": sum(
        row["status"] == "succeeded" for row in result
    )}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("collect", "prep"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--code-version", required=True)
    parser.add_argument("--resume", action="store_true",
                        help="消費台帳と未実施jobを維持して収集を再開")
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    engine = create_engine(os.environ["DATABASE_URL"], hide_parameters=True)
    try:
        if args.action == "collect":
            collect(engine, args.root, args.code_version, resume=args.resume)
        else:
            prepare(engine, args.root, args.code_version)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
