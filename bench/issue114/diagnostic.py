"""旧1件・新2件でsnapshot→aggregate→reportを照合する。DBへの統計登録はしない。"""

import json
import os
from pathlib import Path

from bench.issue114.output_directories import anonymous_directories
from bench.issue114.production import CODE, ROOT, database, read, save
from bench.issue114.terrain_statistics import human_holds
from bench.issue122 import statistics
from bench.issue122.statistics import ensure_snapshot
from sqlalchemy.orm import Session

from colorstats import privacy_review
from colorstats.stats.aggregate import aggregate
from colorstats.stats.aggregate_cli import load_settings
from colorstats.stats.region_quality import load
from colorstats.stats.report import report


def main():
    os.umask(0o077)
    old = read(Path("/mnt/data/derived/stats/issue122-terrain-20261109-v1/selection.json"))
    held = set(human_holds()["asset_ids"])
    selected = [row for row in old["assets"] if row["status"] == "terrain_selected"
                and row["asset_id"] not in held][:1]
    records = {}
    for host in ("ubuntu1", "ubuntu2"):
        records.update(read(ROOT / host / "records.json"))
    db = database()
    try:
        with Session(db) as session:
            for row in read(ROOT / "plan.json")["rows"]:
                record = records.get(row["asset_id"], {})
                if (len(selected) == 3 or row.get("analysis_domain") != "real_terrain"
                        or row["asset_id"] in held or not record.get("terminal")
                        or record["privacy_verdict"]["decision"] != "accepted"):
                    continue
                item = privacy_review.selection(session, row["asset_id"],
                                                record["privacy_review_run_id"])
                item.update(asset_id=row["asset_id"], prep_run_id=row["input_run_id"],
                            **{key: record[key] for key in (
                                "segment_run_id", "shade_run_id", "color_run_id")})
                selected.append(item)
        if len(selected) != 3:
            print("diagnostic_waiting_for_terrain_samples", flush=True)
            return
        selection = {"taxonomy_version": old["taxonomy_version"], "assets": selected,
                     "policy_version": "issue114-terrain-diagnostic-v1",
                     "subject_attribute_run_ids": old.get("subject_attribute_run_ids", [])}
        statistics.OUTPUT = ROOT / "diagnostic"
        with anonymous_directories():
            snapshot, manifest = ensure_snapshot(db, selection, load(CODE),
                                                  policy="issue114-terrain-diagnostic-v1")
            settings = load_settings(CODE / "configs/stats.yaml",
                                     CODE / "configs/collection_targets.yaml", CODE / "taxonomy")
            settings["strata"] = [row for row in settings["strata"]
                                  if row["attributes"]["domain"] == "real_terrain"]
            data = aggregate(snapshot, manifest["snapshot_id"], settings)
            rendered = report(snapshot, manifest["snapshot_id"], data, settings)
            assert all(row["conditions"]["domain"] == "real_terrain" and
                       set(row["target_parts"]) <= {"tree", "water"} for row in data["rows"])
            save(statistics.OUTPUT / "report.json", rendered)
            result = {"samples": 3, "old_samples": 1, "new_samples": 2,
                      "snapshot_id": manifest["snapshot_id"], "rows": len(data["rows"]),
                      "database_statistics_registered": 0, "building": "未集計"}
            save(statistics.OUTPUT / "summary.json", result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        db.dispose()


if __name__ == "__main__":
    main()
