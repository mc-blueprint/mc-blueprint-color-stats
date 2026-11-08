"""#129専用運用。完全バックアップ・固定計画・既存review workerを使う。"""

import argparse
import hashlib
import json
import os
import signal
import time
import uuid
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from bench.issue117.production_audit import audit_call
from bench.issue129.review import summarize
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from colorstats import image_gate as gate
from colorstats.api_budget import BUDGET_KEY, NUSD, PRICING, V2_CAP, digest
from colorstats.queue import Queue
from colorstats.queue.worker import Worker
from colorstats.schema.models import ApiBudget, ApiCall, Asset, Job, ProcessingRun

OLD = Path("/mnt/data/derived/issue117-production-20261107T0918Z")


def save(path, value):
    temporary = path.with_suffix(".writing")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, default=str)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def baseline(connection, table):
    assert table in {"asset", "processing_run"}
    return dict(connection.execute(text(
        f"SELECT id::text, md5(row_to_json(t)::text) FROM {table} t ORDER BY id",
    )).all())


def freeze(engine, root, code_version, *, input_reference=None):
    """DBを変更せず完全dumpと旧行・母集団・送信条件を固定する。"""
    assert not (root / "plan.json").exists()
    dump = root / "before.dump"
    assert dump.stat().st_size > 0 and (root / "before.dump.list").stat().st_size > 0
    assert load(root / "backup.json")["sha256"] == hashlib.sha256(dump.read_bytes()).hexdigest()
    cohorts = load(OLD / "cohorts.json")
    assets = cohorts["old"] + cohorts["new"]
    assert len(cohorts["old"]) == 7626 and len(cohorts["new"]) == 2600
    assert len(assets) == len(set(assets)) == 10226
    review = load(root / "review-freeze.json")
    reference = load(input_reference / "plan.json") if input_reference else None
    if reference:
        assert reference["assets"] == assets
        assert reference["identity"]["preprocess_version"] == gate.PREPROCESS
        assert reference["review_sha256"] == hashlib.sha256(
            (root / "review-freeze.json").read_bytes()).hexdigest()
    review_ids = [row["asset_id"] for row in review["records"]]
    assert len(review_ids) == len(set(review_ids)) == 110 and set(review_ids) <= set(assets)
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0009"
        for table in ("asset", "processing_run"):
            path = root / f"before-{table}.json"
            current = baseline(connection, table)
            if input_reference:
                assert all(current.get(key) == value for key, value in load(
                    input_reference / f"before-{table}.json").items())
            if path.exists():
                assert all(current.get(key) == value for key, value in load(path).items())
            else:
                save(path, current)
    holds, input_manifest = {}, {}
    legacy_jobs = {} if reference else load(OLD / "plan.json")["jobs"]
    with Session(engine) as session:
        budget = session.get(ApiBudget, BUDGET_KEY)
        assert budget.pricing == PRICING and not budget.stopped
        assert 0 < budget.cap_nusd <= 50 * NUSD
        assert not session.scalar(select(ApiCall.id).where(
            ApiCall.budget_key == BUDGET_KEY, ApiCall.cost_nusd.is_(None)))
        for identifier in assets:
            try:
                asset = session.get(Asset, uuid.UUID(identifier))
                gate.check_input(session, SimpleNamespace(
                    asset_id=asset.id, payload={"source_sha256": asset.sha256}))
                if reference:
                    if identifier in reference["holds"]:
                        holds[identifier] = reference["holds"][identifier]
                        continue
                    fixed = reference["inputs"][identifier]
                    assert asset.sha256 == fixed["source_sha256"]
                    input_manifest[identifier] = {
                        "source_sha256": asset.sha256,
                        "identity": {**gate.identity(b""),
                                     "input_sha256": fixed["identity"]["input_sha256"]},
                    }
                    continue
                raw = Path(asset.storage_path).read_bytes()
                if hashlib.sha256(raw).hexdigest() != asset.sha256:
                    raise ValueError("入力SHA不一致")
                if identifier in legacy_jobs:
                    original = session.get(Job, uuid.UUID(legacy_jobs[identifier]))
                    payload = original.payload
                    assert original.asset_id == asset.id and payload["kind"] == "image_gate"
                    assert payload["source_sha256"] == asset.sha256
                    assert payload["identity"]["preprocess_version"] == gate.PREPROCESS
                    image = (Path(payload["artifact_dir"]) / f"{original.id}.png").read_bytes()
                    assert hashlib.sha256(image).hexdigest() == payload["identity"]["input_sha256"]
                else:
                    image = gate.normalize(raw)
                input_manifest[identifier] = {"source_sha256": asset.sha256,
                                              "identity": gate.identity(image)}
            except Exception as error:
                holds[identifier] = type(error).__name__
                session.rollback()
    save(root / "input-checkpoint.json", {
        "inputs": input_manifest, "holds": holds, "identity": gate.identity(b""),
        "code_version": code_version,
    })
    for row in review["records"]:
        if row["asset_id"] not in input_manifest:
            assert row["image_gate_run_id"] is None
            assert row["image_gate_verdict"]["reason"] == "gate_enqueue_failed"
            continue
        fixed = input_manifest[row["asset_id"]]
        assert row["sha256"] == fixed["source_sha256"]
        assert row["image_gate_identity"]["input_sha256"] == fixed["identity"]["input_sha256"]
    plan = {"assets": assets, "cohorts": cohorts, "jobs": {}, "holds": holds,
            "inputs": input_manifest, "review_ids": review_ids,
            "code_version": code_version, "identity": gate.identity(b""),
            "started_at": datetime.now(UTC).isoformat(),
            "backup_sha256": hashlib.sha256(dump.read_bytes()).hexdigest(),
            "review_sha256": hashlib.sha256((root / "review-freeze.json").read_bytes()).hexdigest(),
            "dependency": load(root / "dependency.json")}
    if input_reference:
        plan["input_reference"] = {
            "plan_sha256": hashlib.sha256((input_reference / "plan.json").read_bytes()).hexdigest(),
            "inputs_sha256": digest(reference["inputs"]),
            "code_version": reference["code_version"],
        }
    save(root / "plan.json", plan)
    save(root / "freeze-proof.json", {
        "assets": len(assets), "sendable": len(input_manifest), "holds": len(holds),
        "review_sendable": sum(identifier in input_manifest for identifier in review_ids),
        "review_input_holds": sum(identifier in holds for identifier in review_ids),
        "inputs_sha256": digest(input_manifest), "targets_sha256": digest(assets),
        "review_sha256": plan["review_sha256"], "identity": plan["identity"],
        "backup_sha256": plan["backup_sha256"], "dependency": plan["dependency"],
    })
    print("freeze_complete", flush=True)


def state(engine, root):
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        jobs = dict(connection.execute(text(
            "SELECT status,count(*) FROM job WHERE payload->>'artifact_dir'=:directory "
            "GROUP BY status"), {"directory": str(root / "artifacts")}).all())
        costs = dict(connection.execute(text(
            "SELECT coalesce(sum(coalesce(cost_nusd,reserved_nusd)),0) AS parent_nusd, "
            "coalesce(sum(coalesce(cost_nusd,reserved_nusd)) FILTER (WHERE "
            "details->'identity'->'input'->>'policy_version'='image-gate-v2'),0) AS v2_nusd, "
            "count(*) FILTER (WHERE state='sent') AS sent "
            "FROM api_call WHERE budget_key=:key"), {"key": BUDGET_KEY}).mappings().one())
        budget = dict(connection.execute(text(
            "SELECT stopped,cap_nusd FROM api_budget WHERE key=:key"),
            {"key": BUDGET_KEY}).mappings().one())
    return {"at": datetime.now(UTC).isoformat(), "jobs": jobs, **costs, **budget}


def retire(engine, root):
    """停止済み旧候補の未送信jobを終了する。原判定・台帳は保全する。"""
    plan = load(root / "plan.json")
    assert state(engine, root)["sent"] == 0
    queue = Queue(engine)
    identifiers = [uuid.UUID(value) for value in plan["jobs"].values()]
    retired = []
    while claim := queue.claim(("review",), job_ids=identifiers):
        assert claim.payload["kind"] == "image_gate"
        assert claim.payload["artifact_dir"] == str(root / "artifacts")
        queue.fail(claim, "候補更新により未送信のまま終了", retryable=False)
        retired.append(str(claim.id))
    save(root / "retired-jobs-private.json", retired)
    result = state(engine, root)
    assert not result["jobs"].get("pending", 0) and not result["jobs"].get("running", 0)
    save(root / "retirement.json", {**result, "retired_without_api": len(retired)})


def run(engine, root, phase):
    plan = load(root / "plan.json")
    assert plan["identity"] == gate.identity(b"")
    assert plan["review_sha256"] == hashlib.sha256(
        (root / "review-freeze.json").read_bytes()).hexdigest()
    assert os.environ.get("CREDENTIALS_DIRECTORY")
    assert os.environ["COLORSTATS_IMAGE_GATE_CONCURRENCY"] == "4"
    targets = plan["review_ids"][:12] if phase == "smoke" else plan["review_ids"]
    if phase == "full":
        assert load(root / "regression-summary.json")["passed"]
        targets = plan["review_ids"] + [x for x in plan["assets"] if x not in plan["review_ids"]]
    stop = root / f"{phase}.stop"
    assert not stop.exists()
    signal.signal(signal.SIGTERM, lambda *_: stop.touch())
    workers = [Worker(Queue(engine), {"review": "colorstats.image_gate"}, root / "abort",
                      storage_paths={"review": (root,)}) for _ in range(4)]
    active, free = {}, list(range(4))
    pool = ThreadPoolExecutor(4)
    next_report = 0
    reason = "all_terminal"
    try:
        while not stop.exists():
            current = state(engine, root)
            assert current["parent_nusd"] <= 50 * NUSD and current["v2_nusd"] <= V2_CAP
            if current["stopped"]:
                reason = "budget_stopped"
                break
            reservation = gate.MAX_INPUT * max(PRICING[key] for key in (
                "input_nusd", "write_nusd", "write_12h_nusd")) + gate.MAX_OUTPUT * PRICING[
                    "output_nusd"]
            if (current["parent_nusd"] + reservation > current["cap_nusd"]
                    or current["v2_nusd"] + reservation > V2_CAP):
                reason = "near_cap"
                break
            pending = [x for x in targets if x not in plan["jobs"] and x not in plan["holds"]]
            if current["jobs"].get("pending", 0) < 32:
                for identifier in pending[:16]:
                    if stop.exists():
                        break
                    try:
                        job_id = gate.enqueue(Queue(engine), identifier, root / "artifacts",
                                              budget_key=BUDGET_KEY,
                                              code_version=plan["code_version"],
                                              execution_authorized=True)
                        plan["jobs"][identifier] = str(job_id)
                    except Exception as error:
                        plan["holds"][identifier] = type(error).__name__
                        continue
                    with Session(engine) as session:
                        job = session.get(Job, job_id)
                        assert job.payload["identity"] == plan["inputs"][identifier]["identity"]
                        assert job.payload["source_sha256"] == plan["inputs"][identifier][
                            "source_sha256"]
                save(root / "plan.json", plan)
            ids = [uuid.UUID(plan["jobs"][x]) for x in targets if x in plan["jobs"]]
            while free and not stop.exists():
                claim = workers[0].queue.claim(("review",), job_ids=ids)
                if claim is None:
                    break
                slot = free.pop()
                active[pool.submit(workers[slot]._run_claim, claim)] = slot
            if (not active and not pending and not current["jobs"].get("pending", 0)
                    and not current["jobs"].get("running", 0)):
                break
            if time.monotonic() >= next_report:
                save(root / "progress.json", {**current, "phase": phase})
                print(json.dumps(current, default=str), flush=True)
                next_report = time.monotonic() + 60
            if active:
                done, _ = wait(active, timeout=1, return_when=FIRST_COMPLETED)
                for future in done:
                    free.append(active.pop(future))
                    future.result()
            else:
                time.sleep(1)
        else:
            reason = "stop_requested"
    finally:
        pool.shutdown(wait=True)
        for worker in workers:
            worker._stop_prepare()
        save(root / f"{phase}-end.json", {**state(engine, root), "reason": reason})


def report(engine, root):
    plan = load(root / "plan.json")
    review = load(root / "review-freeze.json")["records"]
    by_id = {row["asset_id"]: row for row in review}
    verdicts, transitions, distributions = Counter(), Counter(), {}
    audit, usage = Counter(), Counter()
    selections, cohort_verdicts = [], {"old": Counter(), "new": Counter()}
    with Session(engine) as session:
        old_verdicts = dict(session.execute(select(
            ProcessingRun.parameters["asset_id"].astext,
            ProcessingRun.parameters["verdict"]["decision"].astext,
        ).where(
            ProcessingRun.stage == "review",
            ProcessingRun.parameters["identity"]["policy_version"].astext == "image-gate-v1",
            ProcessingRun.finished_at.is_not(None),
            ProcessingRun.parameters["method"].astext == "api",
        ).order_by(ProcessingRun.finished_at)).all())
        for identifier in plan["assets"]:
            job = (session.get(Job, uuid.UUID(plan["jobs"][identifier]))
                   if identifier in plan["jobs"] else None)
            observation, verdict = None, {"decision": "pending", "reason": "unjudged"}
            if job and job.status == "succeeded":
                run_row = session.get(ProcessingRun, job.run_id)
                parameters = run_row.parameters
                content = Path(parameters["result_path"]).read_bytes()
                assert hashlib.sha256(content).hexdigest() == parameters["result_sha256"]
                assert parameters["identity"] == plan["inputs"][identifier]["identity"]
                saved = json.loads(content)
                observation, verdict = saved["result"], parameters["verdict"]
                if verdict["decision"] == "accepted":
                    selections.append(gate.selection(session, identifier, run_row.id))
            elif identifier in plan["holds"]:
                verdict["reason"] = "input_hold"
            elif job and job.status == "failed":
                verdict["reason"] = "api_or_job_failure"
            verdicts[verdict["decision"]] += 1
            group = "old" if identifier in set(plan["cohorts"]["old"]) else "new"
            cohort_verdicts[group][verdict["decision"]] += 1
            old_state = old_verdicts.get(identifier, "unavailable")
            transitions[old_state + "->" + verdict["decision"]] += 1
            for key in ("target", "subject", "real_people", "black_and_white", "aerial_view"):
                value = (str(observation.get(key))
                         if isinstance(observation, dict) else "unavailable")
                distributions.setdefault(key, Counter())[value] += 1
            if identifier in by_id:
                by_id[identifier].update(v2_observation=observation, v2_verdict=verdict)
        calls = session.scalars(select(ApiCall).where(
            ApiCall.budget_key == BUDGET_KEY,
            ApiCall.details["identity"]["input"]["policy_version"].astext == gate.POLICY_VERSION,
        )).all()
        for call in calls:
            checked = audit_call(call)
            audit.update(checked["errors"])
            if call.endpoint == "responses":
                for key, value in (call.details.get("usage") or {}).items():
                    if type(value) is int:
                        usage[key] += value
        accounting = {"booked_nusd": sum(c.cost_nusd if c.cost_nusd is not None else c.reserved_nusd
                                          for c in calls),
                      "unsettled": sum(c.cost_nusd is None for c in calls), "calls": len(calls)}
    regression = summarize(review)
    previous = summarize([{**row, "v2_observation": row["image_gate_observation"],
                           "v2_verdict": row["image_gate_verdict"]} for row in review])
    regression["v1_groups"] = previous["groups"]
    aerial_policy = {
        "positive": sum(row["aerial_truth"] is True for row in review),
        "held_with_aerial_signal": sum(
            row["aerial_truth"] is True
            and (row.get("v2_observation") or {}).get("aerial_view") is not False
            and row["v2_verdict"]["decision"] == "pending" for row in review),
        "ordinary_accepted": sum(row["aerial_truth"] is False
                                 and row["v2_verdict"]["decision"] == "accepted" for row in review),
    }
    regression["aerial_policy"] = aerial_policy
    regression["passed"] = (
        regression["known_black_and_white"] == {"positive": 9, "missed_or_unknown": 0}
        and regression["aerial_adopted"] == 0
        and aerial_policy["positive"] == aerial_policy["held_with_aerial_signal"] > 0
        and aerial_policy["ordinary_accepted"] > 0
        and not regression["low_saturation_color"]["black_and_white_false_positive"]
        and sum(group["attributes"]["non_target"]["fp"]
                for group in regression["groups"].values()) <= sum(
                    group["attributes"]["non_target"]["fp"]
                    for group in previous["groups"].values())
        and sum(group["attributes"]["black_and_white"]["fp"]
                for group in regression["groups"].values()) <= sum(
                    group["attributes"]["black_and_white"]["fp"]
                    for group in previous["groups"].values())
        and all(group["accepted_reported_problems"] == 0 for group in regression["groups"].values())
        and regression["prediction_coverage"]["unexpected_unavailable"] == 0)
    save(root / "regression-private.json", review)
    save(root / "regression-summary.json", regression)
    unchanged = {}
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        for table in ("asset", "processing_run"):
            before, after = load(root / f"before-{table}.json"), baseline(connection, table)
            unchanged[table] = {"before_rows": len(before),
                                "changed_or_missing": sum(after.get(k) != v
                                                          for k, v in before.items())}
    save(root / "selection-private.json", selections)
    current = state(engine, root)
    complete = (sum(current["jobs"].get(status, 0) for status in ("succeeded", "failed"))
                + len(plan["holds"]) == len(plan["assets"])
                and not current["jobs"].get("pending", 0)
                and not current["jobs"].get("running", 0)
                and not accounting["unsettled"] and not audit
                and all(value["changed_or_missing"] == 0 for value in unchanged.values()))
    save(root / "public-summary.json", {
        **current, "target_assets": len(plan["assets"]), "complete": complete,
        "verdicts": dict(verdicts), "transitions": dict(transitions),
        "cohort_verdicts": {key: dict(value) for key, value in cohort_verdicts.items()},
        "distributions": {key: dict(value) for key, value in distributions.items()},
        "accounting": accounting, "usage": dict(usage), "audit": dict(audit),
        "old_data": unchanged, "regression_passed": regression["passed"],
        "input_holds": dict(Counter(plan["holds"].values())),
    })
    print("report_complete regression_passed=" + str(regression["passed"]), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=(
        "freeze", "retire", "smoke", "regression", "full", "report"))
    parser.add_argument("root", type=Path)
    parser.add_argument("--code-version")
    parser.add_argument("--input-reference", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    os.environ["DATABASE_URL"] = load(Path("/var/lib/colorstats/pilot/database.json"))["url"]
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        if args.action == "freeze":
            freeze(engine, args.root, args.code_version, input_reference=args.input_reference)
        elif args.action == "retire":
            retire(engine, args.root)
        elif args.action == "report":
            report(engine, args.root)
        else:
            run(engine, args.root, args.action)
    finally:
        engine.dispose()
