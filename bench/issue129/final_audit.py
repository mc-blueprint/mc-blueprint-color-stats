"""全量終了時の費用内訳とv1原判定artifactを読取り専用で確認する。"""

import argparse
import hashlib
import os
from collections import Counter
from pathlib import Path

from bench.issue129.production import load, save
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from colorstats.api_budget import BUDGET_KEY, V2_CAP, V2_POLICY
from colorstats.schema.models import ApiCall, ProcessingRun


def audit(engine, root):
    usage, http, endpoints, models, efforts = (Counter() for _ in range(5))
    actual, upper, reserved, unknown = 0, 0, 0, 0
    old_count, old_missing, old_changed = 0, 0, 0
    with Session(engine) as session:
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        calls = session.scalars(select(ApiCall).where(
            ApiCall.budget_key == BUDGET_KEY,
            ApiCall.details["identity"]["input"]["policy_version"].astext == V2_POLICY,
        ))
        for call in calls:
            details = call.details
            if call.cost_nusd is None:
                reserved += call.reserved_nusd
            elif details.get("reconciliation", {}).get("basis") == "reservation_upper_bound":
                upper += call.cost_nusd
            else:
                actual += call.cost_nusd
            unknown += details.get("outcome") == "unknown"
            endpoints[call.endpoint] += 1
            http[str(details.get("status", "unavailable"))] += 1
            if call.endpoint != "responses":
                continue
            if details.get("status") == 200:
                models[str(details.get("returned_model"))] += 1
                efforts[str(details.get("returned_effort"))] += 1
            value = details.get("usage") or {}
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                if type(value.get(key)) is int:
                    usage[key] += value[key]
            for key in ("cached_tokens", "cache_write_tokens"):
                count = (value.get("input_tokens_details") or {}).get(key)
                if type(count) is int:
                    usage[key] += count
            count = (value.get("output_tokens_details") or {}).get("reasoning_tokens")
            if type(count) is int:
                usage["reasoning_tokens"] += count
        for parameters in session.scalars(select(ProcessingRun.parameters).where(
            ProcessingRun.stage == "review", ProcessingRun.finished_at.is_not(None),
            ProcessingRun.parameters["kind"].astext == "image_gate",
            ProcessingRun.parameters["identity"]["policy_version"].astext == "image-gate-v1",
        )):
            old_count += 1
            path = Path(parameters["result_path"])
            if not path.is_file():
                old_missing += 1
            elif hashlib.sha256(path.read_bytes()).hexdigest() != parameters["result_sha256"]:
                old_changed += 1
    result = {
        "actual_usage_nusd": actual, "upper_bound_nusd": upper,
        "unsettled_reserved_nusd": reserved, "booked_nusd": actual + upper + reserved,
        "additional_cap_nusd": V2_CAP,
        "additional_remaining_nusd": V2_CAP - actual - upper - reserved,
        "unknown_calls": unknown, "usage": dict(usage), "http": dict(http),
        "endpoints": dict(endpoints), "returned_models": dict(models),
        "returned_efforts": dict(efforts),
        "v1_artifacts": {"checked": old_count, "missing": old_missing, "changed": old_changed},
    }
    save(root / "final-accounting.json", result)
    print(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    engine = create_engine(load(Path("/var/lib/colorstats/pilot/database.json"))["url"])
    try:
        audit(engine, args.root)
    finally:
        engine.dispose()
