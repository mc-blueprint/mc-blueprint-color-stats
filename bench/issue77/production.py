"""固定設定の手動collectを1ワーカーで実行し、試行台帳と前後状態を保存する。"""

import argparse
import hashlib
import json
import os
import subprocess
import traceback
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from colorstats.collect import bias
from colorstats.collect.coverage import coverage
from colorstats.collect.measurement import report
from colorstats.collect.targets import load_targets
from colorstats.queue import Queue
from colorstats.queue.storage import storage_available
from colorstats.queue.worker import Worker
from colorstats.schema.models import Asset, Job, ProcessingRun

ROOT = Path(__file__).resolve().parents[2]


def save(path, value):
    """新規artifactだけを作成する。接続情報や例外本文は受け取らない。"""
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def selected_jobs(session, measurement_id):
    return session.scalars(
        select(Job)
        .where(
            Job.stage == "collect",
            Job.payload["bias"]["measurement"]["id"].astext == measurement_id,
        )
        .order_by(Job.created_at, Job.id)
    ).all()


def state(engine, config):
    """収集前後の状態を同一READ ONLY snapshotで読む。"""
    with Session(engine) as session, session.begin():
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        active = [
            dict(row)
            for row in session.execute(
                select(Job.stage, Job.status, func.count().label("count"))
                .where(Job.status.in_(["pending", "running"]))
                .group_by(Job.stage, Job.status)
            ).mappings()
        ]
        unfinished = session.scalar(
            select(func.count())
            .select_from(ProcessingRun)
            .where(
                ProcessingRun.stage == "collect",
                (ProcessingRun.finished_at.is_(None))
                | ProcessingRun.parameters["state"].astext.in_(["running", "prepared", "stopped"]),
            )
        )
        counts = (
            session.execute(
                select(
                    func.count(Asset.id).label("assets"),
                    func.count(Asset.sha256.distinct()).label("sha"),
                    func.count(Asset.subject_id.distinct()).label("subjects"),
                )
            )
            .mappings()
            .one()
        )
        return {
            "at": datetime.now(UTC),
            "active_jobs": active,
            "unfinished_collect": unfinished,
            "counts": dict(counts),
            "coverage": coverage(session, config),
        }


def job_summary(jobs):
    return {
        "statuses": dict(Counter(job.status for job in jobs)),
        "attempts": sum(job.attempts for job in jobs),
        "jobs": [
            {
                "id": str(job.id),
                "status": job.status,
                "attempts": job.attempts,
                "run_id": str(job.run_id) if job.run_id else None,
                "stratum": job.payload["request"]["stratum"],
                "provider": job.payload["request"]["provider"],
            }
            for job in jobs
        ],
    }


def summarize(result, config):
    """試行台帳から層・供給元別の分母を出す。要求なしは未測定とする。"""
    rows, total = [], Counter()
    for layer in config["strata"]:
        detail = result["strata"].get(layer["id"], {})
        for provider in config["search"]["providers"]:
            counts, stops, exclusions, states = Counter(), Counter(), Counter(), Counter()
            for history in detail.get("history", []):
                if history["request"]["provider"] != provider:
                    continue
                counts.update(history["counts"])
                states[history["state"]] += 1
                if history.get("stop_reason"):
                    stops[history["stop_reason"]] += 1
                exclusions.update(history.get("d15_exclusions", {}))
            total.update(counts)
            rows.append(
                {
                    "stratum": layer["id"],
                    "provider": provider,
                    "counts": dict(counts),
                    "measured": counts["api_requests"] > 0,
                    "states": dict(states),
                    "stops": dict(stops),
                    "d15_exclusions": dict(exclusions),
                    "eligible_new_sha_per_api_request": (
                        counts["eligible_new_sha"] / counts["api_requests"]
                        if counts["api_requests"]
                        else None
                    ),
                }
            )
    return {
        "totals": dict(total),
        "strata_providers": rows,
        "confirmed_subjects_by_stratum": {
            key: detail["counts"]["confirmed_subjects"] for key, detail in result["strata"].items()
        },
    }


def verify_roots(code):
    import yaml

    raw = yaml.safe_load((code / "configs/storage.yaml").read_text())["storage"]["raw"]
    roots = tuple(Path(item["path"]) for item in raw)
    for item in raw:
        actual = subprocess.check_output(
            ["findmnt", "-n", "-o", "UUID", "-T", item["path"]], text=True
        ).strip()
        if item["host"] != "ubuntu-1" or actual != item["uuid"]:
            raise ValueError("raw媒体と固定設定が一致しません")
        if not os.access(item["path"], os.W_OK):
            raise PermissionError("raw媒体への書込み権がありません")
    if not storage_available("collect", roots):
        raise ValueError("保存先監視がcollectを許可していません")
    return roots


def execute(engine, code, output, version):
    config = load_targets(code / "bench/issue77/targets.yaml", code / "taxonomy")
    measurement_id = config["measurement"]["id"]
    before = state(engine, config)
    save(output / "before.json", before)
    if any(row["stage"] == "collect" for row in before["active_jobs"]):
        raise ValueError("開始前のcollectジョブが残っています")
    if before["unfinished_collect"]:
        raise ValueError("開始前の未完了collect runが残っています")
    with Session(engine) as session:
        if selected_jobs(session, measurement_id):
            raise ValueError("同じ測定IDのジョブが既に存在します")
    roots = verify_roots(code)
    save(
        output / "implementation.json",
        {
            "code_version": version,
            "files": {
                str(p.relative_to(code)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted((code / "src").rglob("*.py"))
            },
            "settings": {
                name: hashlib.sha256((code / name).read_bytes()).hexdigest()
                for name in (
                    "configs/source_policy.yaml",
                    "configs/storage.yaml",
                    "bench/issue77/targets.yaml",
                )
            },
        },
    )
    queue = Queue(engine)
    worker = Worker(
        queue,
        {"collect": "colorstats.collect.bias"},
        output / "stop",
        storage_paths={"collect": roots},
    )
    started, completed, seen = monotonic(), 0, set()
    try:
        while True:
            if (output / "stop").exists() or not storage_available("collect", roots):
                raise RuntimeError("測定が停止されました")
            planned = bias.plan(
                queue,
                config,
                policy_path=code / "configs/source_policy.yaml",
                storage_config=code / "configs/storage.yaml",
                host="ubuntu-1",
                code_version=version,
                seed=77,
            )
            if set(planned) <= seen:
                break
            seen.update(planned)
            while True:
                if (output / "stop").exists() or not storage_available("collect", roots):
                    raise RuntimeError("測定が停止されました")
                claim = queue.claim(["collect"], job_ids=planned)
                if claim is None:
                    break
                worker._run_claim(claim)
                completed += 1
                with Session(engine) as session:
                    checkpoint = job_summary(selected_jobs(session, measurement_id))
                checkpoint.update(at=datetime.now(UTC), seconds=monotonic() - started)
                path = output / "progress.tmp"
                path.write_text(json.dumps(checkpoint, default=str), encoding="utf-8")
                path.replace(output / "progress.json")
                print(
                    json.dumps(
                        {
                            "completed_attempts": completed,
                            "statuses": checkpoint["statuses"],
                            "seconds": round(monotonic() - started, 3),
                        }
                    ),
                    flush=True,
                )
    finally:
        worker._stop_prepare()
    with Session(engine) as session, session.begin():
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        result = report(session, measurement_id)
        jobs = job_summary(selected_jobs(session, measurement_id))
    save(output / "measurement.json", result)
    summary = summarize(result, config)
    summary.update(measurement_id=measurement_id, seconds=monotonic() - started, jobs=jobs)
    save(output / "summary.json", summary)
    after = state(engine, config)
    save(output / "after.json", after)
    if after["unfinished_collect"] or any(
        job["status"] in ("pending", "running") for job in jobs["jobs"]
    ):
        raise ValueError("測定の未完了ジョブまたはrunがあります")
    print(
        json.dumps(
            {
                "complete": True,
                "seconds": summary["seconds"],
                "totals": summary["totals"],
                "jobs": jobs["statuses"],
            }
        ),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--code-version", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    engine = create_engine(os.environ["DATABASE_URL"], hide_parameters=True)
    try:
        execute(engine, ROOT, args.output, args.code_version)
    except Exception as error:
        failure = {
            "error": type(error).__name__,
            "frames": [
                [Path(frame.filename).name, frame.lineno]
                for frame in traceback.extract_tb(error.__traceback__)
            ],
        }
        save(args.output / "failure.json", failure)
        print(json.dumps(failure), flush=True)
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
