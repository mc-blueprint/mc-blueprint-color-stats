"""python -m colorstats.collect.bias_cliで計画と網羅率を出力する。"""

import argparse
import json
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from colorstats.collect.bias import plan
from colorstats.collect.coverage import coverage
from colorstats.collect.targets import load_targets
from colorstats.queue import Queue


def main():
    parser = argparse.ArgumentParser(description="収集計画と層別網羅率")
    parser.add_argument("--targets", type=Path, default=Path("configs/collection_targets.yaml"))
    parser.add_argument("--taxonomy", type=Path, default=Path("taxonomy"))
    commands = parser.add_subparsers(dest="command", required=True)
    planner = commands.add_parser("plan")
    planner.add_argument("--policy", type=Path, default=Path("configs/source_policy.yaml"))
    planner.add_argument("--storage", type=Path, required=True)
    planner.add_argument("--host", required=True)
    planner.add_argument("--code-version", required=True)
    planner.add_argument("--seed", type=int, default=0)
    reporter = commands.add_parser("report")
    reporter.add_argument("--output", type=Path)
    reporter.add_argument("--measurement-id")
    args = parser.parse_args()
    config = load_targets(args.targets, args.taxonomy)
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        if args.command == "plan":
            result = {
                "job_ids": [
                    str(job_id)
                    for job_id in plan(
                        Queue(engine),
                        config,
                        policy_path=args.policy,
                        storage_config=args.storage,
                        host=args.host,
                        code_version=args.code_version,
                        seed=args.seed,
                    )
                ]
            }
        else:
            with Session(engine) as session:
                if args.measurement_id:
                    from colorstats.collect.measurement import report

                    result = report(session, args.measurement_id)
                else:
                    result = coverage(session, config)
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.command == "report" and args.output:
            args.output.write_text(output + "\n", encoding="utf-8")
        else:
            print(output)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
