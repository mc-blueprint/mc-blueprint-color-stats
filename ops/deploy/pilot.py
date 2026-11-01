"""M1の後続stage投入と実測レポート。既存キューの再投入・確定契約を使う。"""

import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import sleep

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from colorstats.collect.bias import plan
from colorstats.collect.coverage import coverage
from colorstats.collect.targets import load_targets
from colorstats.queue import Queue
from colorstats.schema.models import Asset, Job, ProcessingRun


def enqueue_analysis(queue: Queue, derived: Path, version: str) -> dict:
    """成功prepの不変パスをcolorへ渡す。失敗・成功済みjobは初期化しない。"""
    counts = Counter()
    with Session(queue.engine) as session:
        assets = session.scalars(select(Asset)).all()
        prep_runs = {
            job.id: run
            for job, run in session.execute(
                select(Job, ProcessingRun)
                .join(ProcessingRun, Job.run_id == ProcessingRun.id)
                .where(Job.stage == "prep", Job.status == "succeeded")
            )
        }
        for asset in assets:
            target = derived / "pilot-m1" / str(asset.id) / "prep.jpg"
            payload = {
                "input_path": asset.storage_path,
                "derived_path": str(target),
                "license_class": asset.license_class,
                "taxonomy_version": asset.taxonomy_version,
            }
            digest = config_hash("prep", payload, version)
            prep_id = queue.enqueue("prep", asset.id, digest, payload)
            counts["prep"] += 1
            if prep_id not in prep_runs:
                continue
            run = prep_runs[prep_id]
            payload = {
                "input_path": run.output_paths[str(target)],
                "input_run_id": str(run.id),
                "output_path": str(target.with_name("color.json")),
                "license_class": asset.license_class,
                "taxonomy_version": asset.taxonomy_version,
            }
            queue.enqueue("color", asset.id, config_hash("color", payload, version), payload)
            counts["color"] += 1
    return dict(counts)


def config_hash(stage: str, payload: dict, version: str) -> str:
    return hashlib.sha256(
        json.dumps([stage, payload, version], sort_keys=True).encode()
    ).hexdigest()


def report(engine, config: dict) -> dict:
    """DBの実績・失敗と参照済みファイルの容量を読み取る。未参照ファイルは含めない。"""
    with Session(engine) as session:
        result = coverage(session, config)
        result["recorded_at"] = datetime.now(UTC).isoformat()
        jobs = session.scalars(select(Job)).all()
        result["jobs"] = dict(Counter(f"{j.stage}:{j.status}" for j in jobs))
        result["failures"] = dict(Counter(
            f"{j.stage}:{j.failure_reason}" for j in jobs if j.failure_reason
        ))
        runs = session.scalars(select(ProcessingRun)).all()
        result["skipped"] = dict(Counter(
            row["reason"] for run in runs for row in run.parameters.get("skipped", [])
        ))
        sizes = {}
        for stage in ("collect", "prep", "color"):
            selected = [run for run in runs if run.stage == stage]
            paths = {path for run in selected for path in run.output_paths.values()}
            total = 0
            errors = []
            for path in sorted(paths):
                try:
                    total += Path(path).stat().st_size
                except OSError as error:
                    errors.append({"path": path, "error": type(error).__name__})
            sizes[stage] = {
                "runs": len(selected),
                "seconds": sum((r.finished_at - r.started_at).total_seconds() for r in selected),
                "bytes": total,
                "files": len(paths),
                "file_errors": errors,
                "capacity_complete": not errors,
            }
        result["stages"] = sizes
        result["database_bytes"] = session.scalar(
            text("SELECT pg_database_size(current_database())")
        )
        result["table_bytes"] = int(session.scalar(text(
            "SELECT sum(pg_total_relation_size(oid)) FROM pg_class "
            "WHERE relnamespace=current_schema()::regnamespace AND relkind='r'"
        )))
    return result


def main():
    parser = argparse.ArgumentParser(description="M1パイロットの投入・実測")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--derived", type=Path, default=Path("/mnt/data/derived"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--analysis-version", help="解析設定が同じ再配備では既存の識別子を維持する")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    config = load_targets(args.state / "targets.yaml", args.root / "taxonomy")
    engine = create_engine(os.environ["DATABASE_URL"])
    queue = Queue(engine)
    stop = args.state / "scheduler.stop"
    try:
        while not stop.exists():
            if args.run:
                with Session(engine) as session:
                    active = session.scalar(select(func.count()).select_from(Job).where(
                        Job.stage == "collect", Job.status.in_(["pending", "running"])
                    ))
                if not active:
                    seed_path = args.state / "seed.json"
                    seed = json.loads(seed_path.read_text()) if seed_path.exists() else 0
                    if seed < 20:
                        ids = plan(
                            queue, config,
                            policy_path=args.root / "configs/source_policy.yaml",
                            storage_config=args.root / "configs/storage.yaml",
                            host="ubuntu-1", code_version=args.version, seed=seed,
                        )
                        # 次の周回は別探索。成功・失敗済みjobはそのまま残す。
                        seed_path.write_text(json.dumps(seed + 1))
                        print(json.dumps({"seed": seed, "planned": len(ids)}), flush=True)
                # 共有が未整備でも収集は継続し、解析はマウント確認後だけ投入する。
                if args.derived.is_mount():
                    enqueue_analysis(queue, args.derived, args.analysis_version or args.version)
            snapshot = report(engine, config)
            temporary = args.state / "report.tmp"
            temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
            temporary.replace(args.state / "report.json")
            if not args.run:
                break
            for _ in range(60):
                if stop.exists():
                    break
                sleep(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
