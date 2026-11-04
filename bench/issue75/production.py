"""#75の固定snapshot検証・Queue登録・再投入照合。接続情報は表示しない。"""

import argparse
import json
import os
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path
from time import monotonic

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from colorstats.queue import Queue
from colorstats.schema.models import Job, ProcessingRun, ProcessingRunInput, RuleStat
from colorstats.stats import aggregate as handler
from colorstats.stats.aggregate_cli import load_settings
from colorstats.stats.aggregate_cli import main as aggregate_cli
from colorstats.stats.snapshot import canonical, digest


def summarize(data):
    support = []
    for row in data["rows"]:
        quality = row["quality"]
        support.append({
            "conditions": row["conditions"], "parts": row["target_parts"],
            "kind": row["distribution"]["kind"], "status": quality["status"],
            **{key: row[key] for key in (
                "sample_count", "subject_count", "effective_sample_size", "weight",
            )},
            **{key: quality[key] for key in (
                "correction_rate", "no_information_rate", "attribute_unknown_rates",
                "missing_target_mass", "unassigned_subjects", "flags",
            )},
        })
    gates = {}
    for domain, role in (("real_building", "wall"), ("real_terrain", "tree")):
        row = next(r for r in support if r["conditions"] == {"domain": domain}
                   and r["parts"] == [role] and r["kind"] == "palette")
        gates[domain] = row | {
            "condition4_role_gate": (row["subject_count"] >= 10
                                    and row["effective_sample_size"] >= 10
                                    and "model_unvalidated" not in row["flags"]),
        }
    statuses = dict(Counter(row["status"] for row in support))
    return {
        "snapshot_id": data["snapshot_id"], "rows": len(support), "statuses": statuses,
        "supported": sum(statuses.get(key, 0) for key in ("direct", "smoothed")),
        "unsupported": statuses.get("unsupported", 0),
        "input_run_count": len(data["input_runs"]),
        "subject_attribute_run_ids": data["subject_attribute_run_ids"],
        "condition4": gates, "condition4_passed": all(
            row["condition4_role_gate"] for row in gates.values()
        ),
        "interpretation": data["support_interpretation"], "support": support,
    }


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        stream.write(canonical(value) + "\n")


def cli(args, output, *, dry=False):
    sys.argv = [
        "aggregate", "--snapshot", str(args.snapshot), "--snapshot-id", args.snapshot_id,
        "--output", str(output),
    ] + (["--dry-run"] if dry else [])
    if aggregate_cli() != 0:
        raise RuntimeError("aggregate CLIが失敗しました")


def audit(engine, job_id, data):
    """自分の成功job・全統計・入力辺をREAD ONLY取引で固定結果と比較する。"""
    with Session(engine) as session, session.begin():
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        job = session.get(Job, job_id)
        if job.status != "succeeded":
            raise ValueError("集計jobが成功していません")
        run = session.get(ProcessingRun, job.run_id)
        if run.finished_at is None or run.failure_reason is not None or run.license_class != "open":
            raise ValueError("集計runが成功していません")
        rows = session.scalars(select(RuleStat).where(
            RuleStat.processing_run_id == run.id,
        )).all()
        actual = [{
            key: getattr(row, key) for key in data["rows"][0]
        } for row in rows]
        if sorted(map(canonical, actual)) != sorted(map(canonical, data["rows"])):
            raise ValueError("DB統計と固定計算結果が一致しません")
        inputs = sorted(str(rid) for rid in session.scalars(select(
            ProcessingRunInput.input_run_id,
        ).where(ProcessingRunInput.run_id == run.id)))
        if inputs != sorted(row["id"] for row in data["input_runs"]):
            raise ValueError("DB入力辺が一致しません")
        if session.scalar(select(func.count()).select_from(RuleStat).where(
            RuleStat.processing_run_id == run.id, RuleStat.confidence_interval.is_not(None),
        )):
            raise ValueError("未計算の信頼区間がSQL NULLではありません")
        return {
            "job_id": str(job.id), "run_id": str(run.id), "rows": len(rows),
            "input_run_count": len(inputs), "attempts": job.attempts,
            "registered_result_hash": digest(sorted(data["rows"], key=canonical)),
            "output_paths": run.output_paths,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["dry", "register"])
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    started = monotonic()
    engine = None
    try:
        if args.mode == "dry":
            first, second = args.root / "dry-1.json", args.root / "dry-2.json"
            cli(args, first, dry=True)
            cli(args, second, dry=True)
            data = json.loads(first.read_text(encoding="utf-8"))
            if data != json.loads(second.read_text(encoding="utf-8")):
                raise ValueError("二重計算が一致しません")
            summary = summarize(data) | {
                "seconds": round(monotonic() - started, 3), "recalculation_equal": True,
                "result_hash": digest(data),
            }
            write(args.root / "dry-summary.json", summary)
        else:
            dry = json.loads((args.root / "dry-1.json").read_text(encoding="utf-8"))
            if dry["snapshot_id"] != args.snapshot_id:
                raise ValueError("事前確認のsnapshotが違います")
            settings = load_settings(Path("configs/stats.yaml"),
                                     Path("configs/collection_targets.yaml"), Path("taxonomy"))
            output = args.root / "statistics.json"
            payload = {"snapshot": str(args.snapshot.resolve()), "snapshot_id": args.snapshot_id,
                       "settings": settings, "output_path": str(output.resolve())}
            stage_hash = handler.config_hash(payload)
            url = URL.create("postgresql+psycopg", database="colorstats")
            os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
            engine = create_engine(url, connect_args={
                "options": "-c lock_timeout=2000 -c application_name=colorstats-issue75",
            })
            with Session(engine) as session:
                before = session.scalar(select(func.count()).select_from(RuleStat))
                active = session.scalar(select(func.count()).select_from(Job).where(
                    Job.stage == "aggregate", Job.status.in_(["pending", "running"]),
                    Job.stage_config_hash != stage_hash,
                ))
            if active:
                raise ValueError("他のaggregate jobが稼働しています")
            cli(args, output)
            queue = Queue(engine, lease=timedelta(minutes=30), timeout=30)
            with Session(engine) as session:
                job = session.scalar(select(Job).where(
                    Job.stage == "aggregate", Job.asset_id.is_(None),
                    Job.stage_config_hash == stage_hash,
                ))
                job_id, status = job.id, job.status
            if status != "succeeded":
                claim = queue.claim(["aggregate"])
                if claim is None or claim.id != job_id:
                    raise ValueError("対象jobをclaimできません")
                try:
                    prepared = handler.prepare(claim)
                    if prepared.data != dry:
                        raise ValueError("登録前再計算がdry-runと違います")
                    queue.renew(claim)
                    run_id = queue.complete(
                        claim, prepared.info,
                        lambda session, run: handler.register(session, run, prepared.data),
                        prepared.files,
                    )
                except Exception as error:
                    queue.fail(claim, type(error).__name__)
                    raise

                def duplicate(session, run):
                    raise ValueError("成功済みなのに再登録が呼ばれました")

                if queue.complete(claim, prepared.info, duplicate) != run_id:
                    raise ValueError("完了再実行が別runになりました")
            first = audit(engine, job_id, dry)
            cli(args, output)
            second = audit(engine, job_id, dry)
            if first != second:
                raise ValueError("再投入で統計が変わりました")
            summary = summarize(dry) | first | {
                "preexisting_rule_stat_rows": before,
                "seconds": round(monotonic() - started, 3),
                "duplicate_enqueue_equal": True, "database_rows_equal": True,
            }
            write(args.root / "registration.json", summary)
        print(json.dumps({k: v for k, v in summary.items() if k != "support"},
                         ensure_ascii=False, allow_nan=False))
        return 0
    except Exception as error:
        print(f"#75実行失敗: {type(error).__name__}", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
