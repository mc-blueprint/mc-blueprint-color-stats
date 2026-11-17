"""クラウドVLM試行の非公開設定と、合成dry-run用CLI。"""

import argparse
import json
import os
import time
from pathlib import Path

from sqlalchemy import create_engine

from colorstats.trial_cli import synthetic_inputs
from colorstats.trial_fake import FakeRunPod, synthetic_plan
from colorstats.trial_inputs import encoded, private_path, sha, write_private
from colorstats.trial_ledger import Budget
from colorstats.trial_runner import Runner, review_material, writer
from colorstats.trial_runpod import RunPod


def execute(plan, *, dry_run=False, authorization=None, resume=False, cleanup=False):
    """設定された1か所へ回収する。実接続前の許可はRunnerで必須確認する。"""
    root = Path(plan["result_root"])
    engine = None
    with writer(root), Budget(plan["budget_ledger"], 20 if plan["measurement"] else 15) as budget:
        backend = (
            FakeRunPod(plan["region"])
            if dry_run
            else RunPod(plan, audit=lambda event: runner.save("transport", event))
        )
        if not dry_run and not cleanup and authorization and plan["purpose"] == "trial":
            engine = create_engine(os.environ["DATABASE_URL"])
        try:
            runner = Runner(
                plan,
                backend,
                fake=dry_run,
                engine=engine,
                authorization=authorization,
                cleanup_only=cleanup,
                budget=budget,
            )
            if resume:
                runner.resume()
            try:
                while True:
                    started = time.monotonic()
                    if runner.tick() in {"complete", "stopped"}:
                        break
                    if any(
                        r["status"] != "closed" and r["cleanup_failures"] >= 2
                        for r in runner.state["resources"]
                    ):
                        runner.stop(runner.state["stop_reason"] or "cleanup_unconfirmed")
                        runner.cleanup_only()
                        break
                    time.sleep(0 if dry_run else max(0, 10 - (time.monotonic() - started)))
            except (KeyboardInterrupt, Exception) as error:
                runner.stop("local_failure")
                runner.save("local_failure", {"error_type": type(error).__name__})
                runner.cleanup_only()
            return {
                "status": runner.state["status"],
                "results": len(runner.state["results"]),
                "estimated_usd": runner.spending(),
                "synthetic": dry_run,
            }
        finally:
            if engine:
                engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo")
    demo.add_argument("--result-root", type=Path, required=True)
    demo.add_argument("--concurrency", type=int, choices=[1, 2], default=1)
    run = sub.add_parser("run")
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--authorization", type=Path)
    run.add_argument("--dry-run", action="store_true")
    mode = run.add_mutually_exclusive_group()
    mode.add_argument("--resume", action="store_true")
    mode.add_argument("--cleanup", action="store_true")
    review = sub.add_parser("review")
    review.add_argument("--plan", type=Path, required=True)
    review.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "review":
        plan = json.loads(args.plan.read_text())
        root = Path(plan["result_root"])
        path = private_path(root, str(args.output.relative_to(root)))
        material = encoded(review_material(plan))
        from colorstats.trial_inputs import add_files, load_manifest

        manifest = load_manifest(root)
        expiry = min(r["local_expires_at"] for r in manifest["images"])
        with writer(root):
            add_files(
                root,
                [
                    {
                        "file": str(path.relative_to(root)),
                        "sha256": sha(material),
                        "expires_at": expiry,
                    }
                ],
            )
            write_private(path, material)
        print(json.dumps({"review_ready": True, "permission_required": True}))
        return
    if args.command == "demo":
        synthetic_inputs(args.result_root)
        result = execute(
            synthetic_plan(args.result_root, concurrency=args.concurrency), dry_run=True
        )
    else:
        result = execute(
            json.loads(args.plan.read_text()),
            dry_run=args.dry_run,
            resume=args.resume,
            cleanup=args.cleanup,
            authorization=json.loads(args.authorization.read_text())
            if args.authorization
            else None,
        )
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] != "complete" and not (
        args.command == "run" and args.cleanup and result["status"] == "stopped"
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
