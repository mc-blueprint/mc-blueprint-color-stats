"""訂正前後の支持・所有範囲・順序依存と全組合せ不足の件数だけを公開する。"""

import json
import sys
from collections import Counter
from pathlib import Path

from colorstats.stats.snapshot import canonical

sys.path.insert(0, str(Path(__file__).resolve().parent))
from correction import PREVIOUS, REVISION, ROOT  # noqa: E402


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    root = Path(sys.argv[1])
    results = REVISION / "results"
    apply = read(results / "apply.json")
    second = {r["asset_id"]: r for r in read(ROOT / "results/scene-exif-apply.json")["assets"]}
    protected = late = hidden = 0
    reasons = Counter()
    for row in apply["assets"]:
        protected += len(row["protected_attributes"])
        for key in row["before"].keys() | row["after"].keys():
            if row["before"].get(key) == row["after"].get(key):
                continue
            assert key in row["owned_attributes"]
            state = row["attributes"][key]
            assert state["state"] == "unknown" and row["after"].get(key) in (None, "", "unknown")
            prior = second[row["asset_id"]]["attributes"].get(key, {})
            late += prior.get("state") == "preserved"
            if prior.get("state") == "preserved" and len({
                e["value"] for e in prior.get("evidence", [])}) > 1:
                hidden += 1
            reasons[key + ":" + state["reason"]] += 1
    before = read(PREVIOUS / "aggregate/registration.json")
    after = read(root / "aggregate/registration.json")
    manifest = read(root / "snapshot/manifest.json")
    old_defs = read(results / "deficits-before.json")
    new_defs = read(results / "deficits-after.json")
    report = read(root / "report/report.json")
    audit = read(results / "preserved-final.json")
    assert audit == read(results / "preserved-before.json")
    assert read(results / "repeat.json")["changes"] == 0
    result = {
        "snapshot_id": manifest["snapshot_id"], "run_id": after["run_id"], "root": str(root),
        "changes": apply["changes"], "attribute_changes": apply["attribute_changes"],
        "correction_reasons": dict(reasons), "protected_attributes": protected,
        "earlier_preserved_values_corrected": late, "hidden_evidence_conflicts_corrected": hidden,
        "idempotent_changes": 0, "old_versions_preserved": True,
        "counts": manifest["counts"],
        "roles": {d: {"before": before["condition4"][d], "after": after["condition4"][d]}
                  for d in ("real_building", "real_terrain")},
        "supported": {"before": before["supported"], "after": after["supported"]},
        "condition4": {"before": before["condition4_passed"], "after": after["condition4_passed"]},
        "deficits": {"previous_list_rows": 907, "before_rows": len(old_defs["rows"]),
                     "after_rows": len(new_defs["rows"]),
                     "terrain_relation_rows": new_defs["terrain_relation_rows"],
                     "before_causes": old_defs["cause_counts_overlapping"],
                     "after_causes": new_defs["cause_counts_overlapping"]},
        "strata": [{"id": s["id"], "subject_mass": s["inferred"]["subject_mass"],
                    "intended_images": s["intended"]["asset_rows"]} for s in report["strata"]],
    }
    with (results / "comparison.json").open("x", encoding="utf-8") as stream:
        stream.write(canonical(result) + "\n")
    target_input = {"snapshot_id": manifest["snapshot_id"],
                    "statistics_hash": report["statistics_hash"],
                    "strata": [{"id": s["id"],
                                "inferred": {"subject_mass": s["inferred"]["subject_mass"]},
                                "intended": {"asset_rows": s["intended"]["asset_rows"]}}
                               for s in report["strata"]]}
    with (results / "targets-input.json").open("x", encoding="utf-8") as stream:
        stream.write(canonical(target_input) + "\n")
    print(canonical(result))


if __name__ == "__main__":
    main()
