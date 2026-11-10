"""#122の旧基準を保全し、新cohortを加えた地形限定の別版を作る。"""

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from uuid import UUID

from bench.issue114.output_directories import anonymous_directories
from bench.issue114.production import CODE, ROOT, database, read
from bench.issue122 import statistics
from sqlalchemy import select
from sqlalchemy.orm import Session

from colorstats import privacy_review
from colorstats.schema.models import Job
from colorstats.stats.snapshot import digest, verify

OLD = Path("/mnt/data/derived/stats/issue122-terrain-20261109-v1")
OLD_SNAPSHOT = "d53765a48d4b20ed77dbf393c04dad33a2601e5996c9718b44778c5e38448f58"
HUMAN_HOLDS_SHA256 = "39d94cd87895b1edd2885bbe4051f38cc40fce4c043ab350c2fbad649ced2e5d"


def human_holds():
    raw = (ROOT / "human/holds-private.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != HUMAN_HOLDS_SHA256:
        raise ValueError("人確認の保留一覧が固定SHAと一致しません")
    return json.loads(raw)


def selection(db, *, old_only=False):
    old = read(OLD / "selection.json")
    plan = read(ROOT / "plan.json")
    fixed = verify(OLD / "snapshot", OLD_SNAPSHOT)
    normalized = {**old, "assets": sorted(old["assets"], key=lambda row: row["asset_id"])}
    if "subject_attribute_run_ids" in old:
        normalized["subject_attribute_run_ids"] = sorted(old["subject_attribute_run_ids"])
    assert digest(normalized) == fixed["selection_hash"]
    assert len(old["assets"]) == len({row["asset_id"] for row in old["assets"]}) == 7607
    proof = human_holds()
    assert proof["proof"]["human_runs_written"] == 0
    assert proof["proof"]["missing_references"] == 110
    held = set(proof["asset_ids"])
    assert len(held) == 110
    old_rows, old_counts = [], Counter()
    for original in old["assets"]:
        row = dict(original)
        if row["asset_id"] in held:
            row = {"asset_id": row["asset_id"], "status": "human_reference_pending"}
        old_counts["old/" + row["status"]] += 1
        old_rows.append(row)
    human = {"held_missing_new_reference": 110, "human_runs_written": 0,
             "proof_hash": digest(proof["proof"]),
             "reason": "当時のprivacy/region run・提示SHA参照不足"}
    base = {"taxonomy_version": old["taxonomy_version"],
            "subject_attribute_run_ids": old.get("subject_attribute_run_ids", []),
            "policy_version": "issue114-terrain-v1"}
    if old_only:
        return {**base, "assets": old_rows}, {"states": old_counts, "stages": {},
                                              "human_review": human, "diagnostic_old_only": True}
    records = {}
    for host in ("ubuntu1", "ubuntu2"):
        subset = read(ROOT / host / "records.json")
        assert not records.keys() & subset.keys()
        records.update(subset)
    expected = {row["asset_id"] for row in plan["rows"] if row["status"] == "ready"}
    assert records.keys() == expected and all(row.get("terminal") for row in records.values())
    assert len(plan["rows"]) == 2600 and plan["counts"]["original_hold"] == 993
    old_ids = {row["asset_id"] for row in old["assets"]}
    assert len(old_ids) == 7607
    assert not old_ids & {row["asset_id"] for row in plan["rows"]}
    rows, counts, stages = old_rows, old_counts, Counter()
    with Session(db) as session:
        for original in plan["rows"]:
            aid = original["asset_id"]
            row = {"asset_id": aid, "status": original["status"]}
            if aid in held:
                row["status"] = "human_reference_pending"
            elif row["status"] == "ready":
                record = records[aid]
                if record["privacy_verdict"]["decision"] != "accepted":
                    row["status"] = "privacy_pending"
                elif original["analysis_domain"] != "real_terrain":
                    row["status"] = "building_not_aggregated"
                else:
                    row.update(privacy_review.selection(session, aid,
                                                        record["privacy_review_run_id"]))
                    row.update({key: record[key] for key in (
                        "segment_run_id", "shade_run_id", "color_run_id")})
                    row["prep_run_id"] = original["input_run_id"]
                    row["status"] = "terrain_selected"
            counts["new/" + row["status"]] += 1
            rows.append(row)
        for aid, record in records.items():
            for stage in ("segment", "shade", "color"):
                run_id = record.get(stage + "_run_id")
                if not run_id:
                    continue
                job = session.scalar(select(Job).where(Job.run_id == UUID(run_id)))
                assert job.status == "succeeded" and str(job.asset_id) == aid and job.stage == stage
                stages[stage] += 1
    assert len(rows) == len({row["asset_id"] for row in rows}) == 10207
    selected = {**base, "assets": rows}
    execution = {"states": counts, "stages": stages, "original_hold": 993,
                 "human_review": human,
                 "comparison_caveat": (
                     "人確認110件の保留を追加したため純粋な画像追加だけの差ではない")}
    return selected, execution


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-only", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    statistics.CODE, statistics.ROOT = CODE, ROOT
    statistics.OUTPUT = ROOT / ("old-held-baseline" if args.old_only else "statistics")
    statistics.OLD, statistics.OLD_SNAPSHOT = OLD, OLD_SNAPSHOT
    statistics.database = database
    statistics.selection = lambda db: selection(db, old_only=args.old_only)
    old_summary = read(OLD / "summary.json")
    with anonymous_directories():
        heading = ("#114 人確認保留を揃えた旧のみの比較基準" if args.old_only
                   else "#114 新cohort追加・地形側比較")
        statistics.main(policy="issue114-terrain-v1", scope_key="issue114_scope", heading=heading,
                        baseline_registration={"supported": old_summary["supported"],
                                               "condition4": old_summary["roles"]})
    if not args.old_only:
        combined = read(statistics.OUTPUT / "comparison.json")
        held_comparison = read(ROOT / "old-held-baseline/comparison.json")
        combined["image_addition_only"] = {
            "old": held_comparison["new"], "new": combined["new"],
            "condition4": {"old": held_comparison["condition4"]["new"],
                           "new": combined["condition4"]["new"]},
            "description": "同じ人確認保留・品質・権利方針の旧のみと旧＋新を比較"}
        combined["human_hold_effect"] = {
            "fixed_old": old_summary, "old_with_holds": held_comparison["new"]}
        statistics.save(statistics.OUTPUT / "comparison.json", combined)
    print(json.dumps({"statistics_complete": True}, ensure_ascii=False), flush=True)
