"""新2,600件を固定し、#122の再開可能なGPU runnerで別runを生成する。"""

import argparse
import hashlib
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from bench.issue122 import production as runner
from bench.issue122 import runtime
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from colorstats import image_gate, privacy_review, retention
from colorstats.analyze import region_policy, segment
from colorstats.schema.models import Asset, Job, ProcessingRun

CODE = Path(__file__).resolve().parents[2]
ROOT = Path("/mnt/data/derived/issue114-terrain-20261110")
ORIGINAL = Path("/mnt/data/derived/issue114-batch1-20261106")
GATE = runner.GATE
LEGACY_HUMAN_HOLDS = {
    "path": "/mnt/data/derived/issue114-terrain-20261110/human/holds-private.json",
    "sha256": "39d94cd87895b1edd2885bbe4051f38cc40fce4c043ab350c2fbad649ced2e5d"}
read, save = runner.read, runner.save


def database():
    return runtime.database()


def implementation():
    return {str(path.relative_to(CODE)): segment._hash(path)
            for directory in ("src", "taxonomy", "configs", "bench/issue122", "bench/issue114")
            for path in sorted((CODE / directory).rglob("*"))
            if path.is_file() and path.suffix in {".py", ".json", ".yaml"}}


def configure():
    runner.ROOT = ROOT
    runner.CODE = CODE
    runner.implementation = implementation


def freeze(db, *, human_sampling, reuse_from=None, models=None):
    runtime.new_root(ROOT)
    if (ROOT / "plan.json").exists():
        raise FileExistsError("固定計画は作成済みです")
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=False)
    decision = read(CODE / "bench/issue121/decision.json")
    handoff = read(CODE / "bench/issue121/handoff.json")
    decision_sha = hashlib.sha256((CODE / "bench/issue121/decision.json").read_text().encode())
    assert handoff["decision_sha256"] == decision_sha.hexdigest()
    scope = decision["downstream"]["terrain_only"]
    assert scope["status"] == "passed" and scope["supported_labels"] == ["water"]
    assert scope["supported_groups"] == ["real_terrain/tree"]
    gate_plan = read(GATE / "plan.json")
    gate_summary = read(GATE / "public-summary.json")
    assert gate_summary["complete"] and gate_summary["regression_passed"]
    assert all(gate_plan["identity"].get(k) == v for k, v in image_gate.identity(b"").items()
               if k != "input_sha256")
    originals = [row for host in ("ubuntu1", "ubuntu2")
                 for row in read(ORIGINAL / host / "manifest.json")["assets"]]
    ids = {row["asset_id"] for row in originals}
    assert len(originals) == len(ids) == 2600
    assert ids == set(gate_plan["cohorts"]["new"])
    assert not ids & set(gate_plan["cohorts"]["old"])
    with db.connect() as connection:
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0009"
        for table in runner.BASELINE_TABLES:
            save(ROOT / ("before-" + table + ".json"), runner.baseline(connection, table))
    counts, planned = Counter(), []
    with Session(db) as session:
        for original in originals:
            row = dict(original)
            aid = UUID(row["asset_id"])
            asset = session.get(Asset, aid)
            assert asset.sha256 == row["sha256"]
            old_review = asset.quality.get("privacy_review")
            assert old_review and old_review["decision"] in {"accepted", "pending"}
            row["original_hold"] = old_review["decision"] == "pending"
            row["status"] = "original_hold" if row["original_hold"] else "ready"
            if row["status"] == "ready" and row["prep_status"] != "succeeded":
                row["status"] = "prep_failed"
            elif row["status"] == "ready" and row["asset_id"] in gate_plan["holds"]:
                row["status"] = "image_input_hold"
            elif row["status"] == "ready":
                job = session.get(Job, UUID(gate_plan["jobs"][row["asset_id"]]))
                assert job.status == "succeeded"
                gate = session.get(ProcessingRun, job.run_id)
                row["image_gate_run_id"] = str(gate.id)
                verdict = gate.parameters["verdict"]
                row["analysis_domain"] = verdict["analysis_domain"]
                if verdict["decision"] != "accepted":
                    row["status"] = "image_gate_" + verdict["decision"]
                else:
                    try:
                        image_gate.selection(session, aid, gate.id)
                        retention.assert_usable(session, aid, images=True)
                    except PermissionError:
                        row["status"] = "rights_or_subject_hold"
            counts[row["status"]] += 1
            planned.append(row)
    assert sum(row["original_hold"] for row in planned) == 993
    ready = [row for row in planned if row["status"] == "ready"]
    partitions = {runtime.PARTITION: ready}
    for host, rows in partitions.items():
        assert len(rows) >= 3
        save(ROOT / host / "inputs.json", rows)
        for directory in ("tmp", "cache"):
            (ROOT / host / directory).mkdir(mode=0o700)
    settings = read(CODE / "bench/issue73/plan.json")["source_settings"]["ade"]
    settings = {"method": region_policy.METHOD, "threshold": 0.35,
                "text_threshold": 0.25, "prompts": settings["prompts"]}
    reused = {}
    if reuse_from is not None:
        runner.check_models(models)
        with Session(db) as session:
            reused = runtime.reused_segments(session, reuse_from, ready, settings, models)
    save(ROOT / "plan.json", {
        "version": runtime.VERSION, "partitions": [runtime.PARTITION],
        "reused_segments": reused, "human_sampling": human_sampling,
        "rows": planned, "counts": counts, "settings": settings,
        "decision_sha256": decision_sha.hexdigest(), "policy_hash": region_policy.policy_hash(),
        "gate_plan_sha256": segment._hash(GATE / "plan.json"),
        "original_manifests": {host: segment._hash(ORIGINAL / host / "manifest.json")
                               for host in ("ubuntu1", "ubuntu2")},
        "created_at": datetime.now(UTC).isoformat(), "api_requests": 0,
        "legacy_human_holds": LEGACY_HUMAN_HOLDS,
    })
    save(ROOT / "execution.json", {"plan_sha256": segment._hash(ROOT / "plan.json"),
                                   "implementation": implementation(),
                                   "implementation_hash": segment._digest(implementation())})
    print({"counts": counts, "partitions": {k: len(v) for k, v in partitions.items()}}, flush=True)


def audit(db, host, limit):
    """全担当入力と成功stage・人物根拠を照合し、件数だけを出力する。"""
    if host != runtime.PARTITION:
        raise ValueError("監査対象hostが必要です")
    plan = runtime.read_plan(ROOT)
    inputs = read(ROOT / host / "inputs.json")
    if inputs != [row for row in plan["rows"] if row["status"] == "ready"]:
        raise ValueError("監査入力が固定manifestと一致しません")
    records = read(ROOT / host / "records.json")
    expected = inputs[:limit] if limit else inputs
    assert set(records) == {row["asset_id"] for row in expected}
    runner.check_access(db, inputs)
    counts, privacy = Counter(), Counter()
    with Session(db) as session:
        for row in expected:
            aid = row["asset_id"]
            record = records[aid]
            assert record.get("terminal")
            review = privacy_review.review(session, aid, record["privacy_review_run_id"])
            assert review.parameters["evidence"]["region_policy_run_id"] == record["segment_run_id"]
            assert review.parameters["evidence"]["image_gate_run_id"] == row["image_gate_run_id"]
            assert review.parameters["verdict"] == record["privacy_verdict"]
            privacy[record["privacy_verdict"]["decision"]] += 1
            for stage in ("segment", "shade", "color"):
                run_id = record.get(stage + "_run_id")
                if not run_id:
                    assert stage != "segment"
                    assert record["privacy_verdict"]["decision"] != "accepted"
                    continue
                job = session.scalar(select(Job).where(Job.run_id == UUID(run_id)))
                run = session.get(ProcessingRun, UUID(run_id))
                assert str(job.asset_id) == aid and job.stage == stage and job.status == "succeeded"
                assert run.finished_at is not None and run.failure_reason is None
                for key in ("input_path", "input_run_id", "input_sha256"):
                    assert job.payload[key] == row[key]
                if stage != "segment":
                    assert job.payload["region_run_id"] == record["segment_run_id"]
                    assert job.payload["privacy_review_run_id"] == record["privacy_review_run_id"]
                counts[stage] += 1
    assert counts["shade"] == counts["color"] == privacy["accepted"]
    result = {"host": host, "target": len(inputs), "terminal": len(records),
              "stages": counts, "privacy": privacy, "failures": 0, "unclosed": 0}
    save(ROOT / host / ("audit-smoke.json" if limit else "audit-full.json"), result)
    print(result, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "run", "check-models", "audit"))
    parser.add_argument("--host", choices=(runtime.PARTITION,), default=runtime.PARTITION)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--sampling", type=Path)
    parser.add_argument("--reuse-from", type=Path)
    parser.add_argument("--models", type=Path, default=Path("/mnt/data/work/issue-40/models"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--execution-name", default="execution.json")
    args = parser.parse_args()
    global ROOT
    ROOT = runtime.new_root(args.root)
    if args.action == "freeze" and args.sampling is None:
        parser.error("freezeには表示前に固定した--samplingが必要です")
    os.umask(0o077)
    configure()
    if args.action == "check-models":
        runner.check_models(args.models)
        print("fixed_models_policy_verified", flush=True)
        return
    db = database()
    try:
        if args.action == "freeze":
            freeze(db, human_sampling=runtime.sampling(args.sampling),
                   reuse_from=args.reuse_from, models=args.models)
        elif args.action == "audit":
            audit(db, args.host, args.limit)
        else:
            if args.host is None:
                parser.error("runには--hostが必要です")
            runner.run(db, args.host, args.models, args.limit,
                       execution_name=args.execution_name, code_prefix="issue114")
    finally:
        db.dispose()


if __name__ == "__main__":
    main()
