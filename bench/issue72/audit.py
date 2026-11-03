"""推定スナップショットの件数・誤結合兆候と#41の限定回帰を集計する。"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def audit(result, identity):
    rows = result["assets"]
    by_id = {r["asset_id"]: r for r in rows}
    sha = defaultdict(set)
    domains = defaultdict(set)
    evidence_missing = []
    for row in rows:
        if row["subject_id"]:
            sha[(row["domain"], row["sha256"])].add(row["subject_id"])
            domains[row["subject_id"]].add(row["domain"])
            if not row["candidates"]:
                evidence_missing.append(row["asset_id"])
    groups = defaultdict(list)
    for aid, value in identity["assets"].items():
        if value["building_name"] and len(value.get("judged_group", [])) > 1:
            groups[value["building_name"]].append(aid)
    regression = {}
    named_subjects = defaultdict(set)
    for name, ids in groups.items():
        found = [by_id[aid] for aid in ids if aid in by_id]
        confirmed = {r["subject_id"] for r in found if r["subject_id"]}
        for sid in confirmed:
            named_subjects[sid].add(name)
        regression[name] = {
            "expected_assets": len(ids), "present": len(found),
            "confirmed": sum(r["state"] == "confirmed" for r in found),
            "candidate": sum(r["state"] == "candidate" for r in found),
            "unknown": sum(r["state"] == "unknown" for r in found),
            "confirmed_subjects": len(confirmed),
        }
    return {
        "counts": dict(Counter(r["state"] for r in rows)),
        "asset_count": len(rows), "sha_count": len({r["sha256"] for r in rows}),
        "confirmed_sha_count": len({
            r["sha256"] for r in rows if r["subject_id"]
        }),
        "confirmed_subject_count": len(domains),
        "confirmed_subjects_by_domain": dict(Counter(
            next(iter(values)) for values in domains.values()
        )),
        "sha_conflicting_groups": sum(len(values) > 1 for values in sha.values()),
        "cross_domain_subjects": sum(len(values) > 1 for values in domains.values()),
        "confirmed_without_evidence": evidence_missing,
        "blocked_new_confirmations": [
            r["asset_id"] for r in rows if r["subject_id"]
            and any(reason in r["reasons"] for reason in (
                "sha_conflict", "location_conflict", "multiple_targets",
            ))
            and "existing_confirmed" not in r["reasons"]
        ],
        "different_named_groups_merged": sum(
            len(names) > 1 for names in named_subjects.values()
        ),
        "issue41_groups": regression,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--identity", type=Path, default=Path(
        "bench/issue41/judgments/building-identity.json"
    ))
    args = parser.parse_args()
    print(json.dumps(audit(
        json.loads(args.snapshot.read_text(encoding="utf-8")),
        json.loads(args.identity.read_text(encoding="utf-8")),
    ), ensure_ascii=False, indent=2))
