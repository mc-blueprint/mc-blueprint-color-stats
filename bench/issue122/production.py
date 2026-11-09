"""固定旧母集団を別runで処理する。個別記録はUbuntuの私有領域へ保存する。"""

import argparse
import hashlib
import json
import os
import pwd
import signal
import socket
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import psycopg
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from colorstats import image_gate, privacy_review, retention
from colorstats.analyze import color, region_policy, segment, shade
from colorstats.queue import Queue
from colorstats.queue.worker import Worker
from colorstats.schema.models import Asset, Job, ProcessingRun

CODE = Path(__file__).resolve().parents[2]
GATE = Path("/mnt/data/derived/issue129-v2-r8-20261108")
ROOT = Path("/mnt/data/derived/issue122-20261109")
OLD = Path("/mnt/data/work/issue-66/production-v2/manifest.json")
BASELINE_TABLES = ("asset", "subject", "subject_candidate", "source", "processing_run", "rule_stat")


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".writing")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, default=str, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    path.chmod(0o600)


def database():
    if socket.gethostname() == "ubuntu-2":
        def connect():
            previous = os.geteuid()
            os.seteuid(pwd.getpwnam("postgres").pw_uid)
            try:
                return psycopg.connect(dbname="colorstats")
            finally:
                os.seteuid(previous)
        return create_engine("postgresql+psycopg://", creator=connect, hide_parameters=True)
    return create_engine(os.environ["DATABASE_URL"], hide_parameters=True)


def implementation():
    return {str(path.relative_to(CODE)): segment._hash(path)
            for directory in ("src", "taxonomy", "configs", "bench/issue122")
            for path in sorted((CODE / directory).rglob("*"))
            if path.is_file() and path.suffix in {".py", ".json", ".yaml"}}


def baseline(connection, table):
    if table not in BASELINE_TABLES:
        raise ValueError("対象外の表です")
    key = ("asset_id::text || '/' || subject_id::text"
           if table == "subject_candidate" else "id::text")
    return dict(connection.execute(text(
        f"SELECT {key},md5(row_to_json(t)::text) FROM {table} t ORDER BY 1",
    )).all())


def check_models(models):
    fixed = read(CODE / "bench/issue121/freeze.json")
    if (region_policy.policy_hash() != fixed["policy_hash"]
            or region_policy.parent_table_reference() != fixed["parent_table"]
            or region_policy.model_configuration(models / "oneformer") != fixed["oneformer"]):
        raise ValueError("#121の固定policy・OneFormerと一致しません")
    for name, files in fixed["models"].items():
        for filename, expected in files.items():
            if segment._hash(models / name / filename) != expected:
                raise ValueError("#121のDINO/SAM2と一致しません")


def freeze(db):
    if (ROOT / "plan.json").exists():
        raise FileExistsError("固定計画は作成済みです")
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    decision = read(CODE / "bench/issue121/decision.json")
    handoff = read(CODE / "bench/issue121/handoff.json")
    decision_hash = hashlib.sha256(
        (CODE / "bench/issue121/decision.json").read_text().encode()).hexdigest()
    assert handoff["decision_sha256"] == decision_hash
    scope = decision["downstream"]["terrain_only"]
    assert scope["status"] == "passed" and scope["supported_labels"] == ["water"]
    assert scope["supported_groups"] == ["real_terrain/tree"]
    gate_summary = read(GATE / "public-summary.json")
    assert gate_summary["complete"] and gate_summary["regression_passed"]
    gate_plan = read(GATE / "plan.json")
    assert all(gate_plan["identity"].get(k) == v for k, v in image_gate.identity(b"").items()
               if k != "input_sha256")
    old = read(OLD)
    rows = old["assets"]
    ids = [row["asset_id"] for row in rows]
    assert len(ids) == len(set(ids)) == 7607
    assert set(ids) <= set(gate_plan["cohorts"]["old"])
    assert not set(ids) & set(gate_plan["cohorts"]["new"])
    assert len(gate_plan["cohorts"]["new"]) == 2600
    with db.connect() as connection:
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0009"
        for table in BASELINE_TABLES:
            save(ROOT / ("before-" + table + ".json"), baseline(connection, table))
    prompts = read(CODE / "bench/issue73/plan.json")["source_settings"]["ade"]["prompts"]
    settings = {"method": region_policy.METHOD, "threshold": 0.35,
                "text_threshold": 0.25, "prompts": prompts}
    counts = Counter()
    planned = []
    with Session(db) as session:
        for original in rows:
            row = dict(original)
            aid = UUID(row["asset_id"])
            asset = session.get(Asset, aid)
            assert asset.sha256 == row["sha256"]
            row["status"] = "ready"
            if row["prep_status"] != "succeeded":
                row["status"] = "prep_failed"
            elif row["asset_id"] in gate_plan["holds"]:
                row["status"] = "image_input_hold"
            else:
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
            if row["status"] == "ready":
                assert segment._hash(row["input_path"]) == row["input_sha256"]
                assert "person_mask" not in row
            counts[row["status"]] += 1
            planned.append(row)
    ready = [row for row in planned if row["status"] == "ready"]
    split = int(len(ready) * 0.4)
    partitions = {"ubuntu1": ready[:split], "ubuntu2": ready[split:]}
    for name, subset in partitions.items():
        assert len(subset) >= 3
        save(ROOT / name / "inputs.json", subset)
    save(ROOT / "plan.json", {"version": "issue122-terrain-v1", "rows": planned,
                              "settings": settings, "implementation": implementation(),
                              "decision_sha256": decision_hash,
                              "policy_hash": region_policy.policy_hash(),
                              "gate_plan_sha256": segment._hash(GATE / "plan.json"),
                              "counts": counts, "created_at": datetime.now(UTC).isoformat(),
                              "new_cohort": 2600, "gate_old_outside_fixed": 19})
    print(json.dumps({"frozen": len(planned), "counts": counts,
                      "partitions": {k: len(v) for k, v in partitions.items()}}), flush=True)


def execute_job(queue, worker, stage, row, payload):
    handler = {"segment": segment, "shade": shade, "color": color}[stage]
    job_id = queue.enqueue(stage, UUID(row["asset_id"]), handler.config_hash(payload), payload)
    while True:
        with Session(queue.engine) as session:
            job = session.get(Job, job_id)
            if job.status == "succeeded":
                return str(job.run_id)
            if job.status == "failed":
                raise RuntimeError("本番stageが失敗しました。私有job記録を確認してください")
        claim = queue.claim((stage,), job_ids=[job_id])
        if claim is None:
            time.sleep(1)
            continue
        worker._run_claim(claim)
        with Session(queue.engine) as session:
            job = session.get(Job, job_id)
            if job.status != "succeeded":
                raise RuntimeError("予期しない失敗のため停止します。自動再送は行いません")


def check_access(db, rows):
    """全担当入力の原画像・prepを検査し、job作成前に配置不備を拒否する。"""
    failures = Counter()
    with Session(db) as session:
        for row in rows:
            asset = session.get(Asset, UUID(row["asset_id"]))
            for kind, path, expected in (
                ("raw", asset.storage_path, row["sha256"]),
                ("prep", row["input_path"], row["input_sha256"]),
            ):
                try:
                    actual = segment._hash(path)
                except OSError as error:
                    failures[kind + "/" + type(error).__name__] += 1
                    continue
                if actual != expected:
                    raise ValueError("担当入力の原画像またはprepのSHAが不一致です")
    if failures:
        print(json.dumps({"input_access_failures": failures}), flush=True)
        raise PermissionError("担当する全原画像・prepの読取りを確認できません")


def run(db, host, models, limit):
    import fcntl

    plan = read(ROOT / "plan.json")
    execution = read(ROOT / "execution-r5.json")
    assert execution["implementation"] == implementation()
    assert execution["plan_sha256"] == segment._hash(ROOT / "plan.json")
    check_models(models)
    directory = ROOT / host
    inputs = read(directory / "inputs.json")
    check_access(db, inputs)
    lock = (directory / "runner.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    stop = directory / "stop"
    assert not stop.exists()
    signal.signal(signal.SIGTERM, lambda *_: stop.touch())
    signal.signal(signal.SIGINT, lambda *_: stop.touch())
    foreign = subprocess.check_output([
        "nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits",
    ], text=True).strip()
    if foreign:
        raise RuntimeError("GPUが使用中です")
    queue = Queue(db, timeout=60)
    worker = Worker(queue, {stage: "colorstats.analyze." + stage
                            for stage in ("segment", "shade", "color")}, stop)
    records_path = directory / "records.json"
    records = read(records_path) if records_path.exists() else {}
    started = time.monotonic()
    completed = 0
    try:
        for row in inputs:
            if stop.exists() or (limit is not None and completed >= limit):
                break
            aid = row["asset_id"]
            if aid in records and records[aid].get("terminal"):
                continue
            record = records.setdefault(aid, {})
            base = {key: row[key] for key in ("input_path", "input_run_id", "input_sha256",
                                             "license_class", "taxonomy_version")}
            base.update(code_version="issue122-" + execution["implementation_hash"][:16],
                        batch=segment._hash(ROOT / "plan.json"))
            if "segment_run_id" not in record:
                payload = {**base, **plan["settings"],
                           "model_paths": {name: str(models / name)
                                           for name in ("dino", "sam2", "oneformer")},
                           "output_path": str(directory / "outputs" / (aid + "-segment.json"))}
                record["segment_run_id"] = execute_job(queue, worker, "segment", row, payload)
                save(records_path, records)
            if "privacy_review_run_id" not in record:
                record["privacy_review_run_id"] = str(privacy_review.write(
                    queue, aid, row["image_gate_run_id"], record["segment_run_id"],
                    code_version=base["code_version"]))
                save(records_path, records)
            with Session(db) as session:
                review = session.get(ProcessingRun, UUID(record["privacy_review_run_id"]))
                record["privacy_verdict"] = review.parameters["verdict"]
                if review.parameters["verdict"]["decision"] == "accepted":
                    approval = privacy_review.selection(session, aid, review.id)
                    region_id = UUID(record["segment_run_id"])
                    regions = color.region_inputs(session, UUID(aid), region_id)
                    policy = color.region_policy_input(session, UUID(aid), region_id)
            if record["privacy_verdict"]["decision"] == "accepted":
                for stage in ("shade", "color"):
                    if stage + "_run_id" in record:
                        continue
                    output = directory / "outputs" / (aid + "-" + stage + ".json")
                    payload = {**base, **approval, "region_run_id": record["segment_run_id"],
                               "regions": regions, "region_policy": policy,
                               "output_path": str(output)}
                    if stage == "shade":
                        payload["method"] = "none"
                    record[stage + "_run_id"] = execute_job(queue, worker, stage, row, payload)
                    save(records_path, records)
            record["terminal"] = True
            save(records_path, records)
            completed += 1
            summary = {"terminal": sum(bool(v.get("terminal")) for v in records.values()),
                       "target": len(inputs), "this_invocation": completed,
                       "privacy": dict(Counter(
                           v["privacy_verdict"]["decision"] for v in records.values()
                           if "privacy_verdict" in v)),
                       "seconds": time.monotonic() - started}
            save(directory / "progress.json", summary)
            print(json.dumps(summary), flush=True)
    finally:
        worker._stop_prepare()
        lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "check-models", "bind", "run"))
    parser.add_argument("--host", choices=("ubuntu1", "ubuntu2"))
    parser.add_argument("--models", type=Path, default=Path("/mnt/data/work/issue-40/models"))
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    os.umask(0o077)
    if args.action == "check-models":
        check_models(args.models)
        print("fixed_models_policy_verified", flush=True)
        return
    db = database()
    try:
        if args.action == "freeze":
            freeze(db)
        elif args.action == "bind":
            path = ROOT / "execution-r5.json"
            assert not path.exists()
            with db.connect() as connection:
                for table in BASELINE_TABLES:
                    before = read(ROOT / ("before-" + table + ".json"))
                    after = baseline(connection, table)
                    assert all(after.get(k) == v for k, v in before.items())
            files = implementation()
            save(path, {"plan_sha256": segment._hash(ROOT / "plan.json"),
                        "implementation": files, "implementation_hash": segment._digest(files)})
            print("execution_bound", flush=True)
        else:
            if args.host is None:
                parser.error("runには--hostが必要です")
            run(db, args.host, args.models, args.limit)
    finally:
        db.dispose()


if __name__ == "__main__":
    main()
