"""本番の追記・既存値保持・支持の変化を読み取り専用で監査する。"""

import json
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from colorstats.schema.models import Asset, Subject
from colorstats.stats.snapshot import canonical, digest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from production import CODE, OLD, ROOT, engine, preserved  # noqa: E402


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    root = Path(sys.argv[1])
    results = ROOT / "results"
    first, second = [read(results / name) for name in
                     ("scene-apply.json", "scene-exif-apply.json")]
    attrs = read(results / "attrs-apply.json")
    before = {r["asset_id"]: r for r in first["assets"]}
    after = {r["asset_id"]: r for r in second["assets"]}
    db = engine(True)
    try:
        with Session(db) as session:
            assets = session.scalars(select(Asset).order_by(Asset.id)).all()
            for asset in assets:
                initial, final = before[str(asset.id)], after[str(asset.id)]
                sid = str(asset.subject_id) if asset.subject_id else None
                assert sid == initial["subject_id"]
                assert asset.scene_attributes == final["after"]
                for key, value in initial["before"].items():
                    if value not in (None, "", "unknown"):
                        assert asset.scene_attributes[key] == value
            for row in attrs["subjects"]:
                subject = session.get(Subject, row["subject_id"])
                for key, column in (("region", "location"), ("era", "era")):
                    assert getattr(subject, column) == row["after"][key]
                    if row["before"][key] is not None:
                        assert row["before"][key] == row["after"][key]
        assert preserved(db) == read(results / "preserved-before.json")
    finally:
        db.dispose()
    changes, bases = Counter(), Counter()
    ids = set()
    for plan in (first, second):
        for row in plan["assets"]:
            for key, value in row["after"].items():
                if value == row["before"].get(key):
                    continue
                ids.add(row["asset_id"])
                changes[key] += 1
                state = row["attributes"][key]
                assert state["state"] == "inferred"
                evidence = state.get("evidence", [])
                basis = sorted({e["basis"] for e in evidence}) or ["commons_category"]
                bases[key + ":" + "+".join(basis)] += 1
    old = read(OLD / "aggregate/registration.json")
    new = read(root / "aggregate/registration.json")
    manifest = read(root / "snapshot/manifest.json")
    old_manifest = read(OLD / "snapshot/manifest.json")
    unchanged_tables = {
        table: manifest["files"][table + ".parquet"] == old_manifest["files"][table + ".parquet"]
        for table in ("provenance", "regions", "observations", "relations", "groups")
    }
    assert all(unchanged_tables.values())
    report = read(root / "report/report.json")
    deficit_before = read(results / "deficits-before-full.json")
    deficit_after = read(results / "deficits-after.json")
    result = {
        "old_snapshot_id": old["snapshot_id"], "new_snapshot_id": manifest["snapshot_id"],
        "old_run_id": old["run_id"], "new_run_id": new["run_id"], "root": str(root),
        "images_changed": len(ids), "attribute_changes": dict(changes),
        "exclusive_basis_counts": dict(bases), "subject_region_changes": len(attrs["changes"]),
        "new_confirmed_images": first["confirmed_images"] + second["confirmed_images"],
        "preserved": True, "state_and_evidence_verified": True,
        "unchanged_snapshot_tables": unchanged_tables,
        "roles": {domain: {"old": old["condition4"][domain], "new": new["condition4"][domain]}
                  for domain in ("real_building", "real_terrain")},
        "supported": {"old": old["supported"], "new": new["supported"]},
        "rows": {"old": old["rows"], "new": new["rows"]},
        "confirmed_subjects": {"old": read(OLD / "snapshot/manifest.json")["counts"]
                               ["confirmed_subjects"],
                               "new": manifest["counts"]["confirmed_subjects"]},
        "condition4": {"old": old["condition4_passed"], "new": new["condition4_passed"]},
        "m3_checks": [{"condition": r["condition"], "status": r["status"]}
                      for r in report["m3_checks"]],
        "deficits": {"old": deficit_before["cause_counts_overlapping"],
                     "new": deficit_after["cause_counts_overlapping"],
                     "rows_before": len(deficit_before["rows"]),
                     "rows_after": len(deficit_after["rows"])},
        "report_sha256_basis": digest(report),
        "strata": [{"id": s["id"], "subject_mass": s["inferred"]["subject_mass"],
                    "subjects": s["inferred"]["confirmed_subjects_after"],
                    "target_subject_deficit": s["inferred"]["subject_deficit"]}
                   for s in report["strata"]],
        "unassigned_subject_reasons": {
            "old": read(OLD / "report/report.json")["classification"]
            ["unassigned_subject_reasons"],
            "new": report["classification"]["unassigned_subject_reasons"],
        },
        "implementation": {str(p.relative_to(CODE)): digest(p.read_text(encoding="utf-8"))
                           for folder in ("src", "configs", "taxonomy")
                           for p in sorted((CODE / folder).rglob("*"))
                           if p.is_file() and "__pycache__" not in p.parts},
    }
    with (results / "comparison-final.json").open("x", encoding="utf-8") as stream:
        stream.write(canonical(result) + "\n")
    print(canonical({k: v for k, v in result.items() if k != "implementation"}))


if __name__ == "__main__":
    main()
