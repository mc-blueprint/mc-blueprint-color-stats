"""#75と同じ合成入力で報告を再現する。引数は未使用の出力ディレクトリ。"""

import json
import platform
import sys
from collections import Counter
from pathlib import Path
from time import monotonic

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.test_stats_aggregate import cell, snapshot

from colorstats.stats.aggregate import aggregate
from colorstats.stats.aggregate_cli import load_settings
from colorstats.stats.report import markdown, report
from colorstats.stats.snapshot import canonical

root = Path(__file__).resolve().parents[2]
output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=False)
settings = load_settings(
    root / "configs/stats.yaml", root / "configs/collection_targets.yaml", root / "taxonomy",
)
settings["strata"] = [
    {"id": "a", "subjects": 100, "attributes": {
        "domain": "real_building", "style": "gothic", "building_type": "temple",
    }},
    {"id": "b", "subjects": 100, "attributes": {
        "domain": "real_building", "style": "modern", "building_type": "house",
    }},
    {"id": "t", "subjects": 100, "attributes": {
        "domain": "real_terrain", "biome_like": "forest",
    }},
]
identifier = snapshot(output / "snapshot", 40, split=10, duplicates=True)
started = monotonic()
statistics = aggregate(output / "snapshot", identifier, settings)
aggregate_seconds = monotonic() - started
(output / "statistics.json").write_text(canonical(statistics) + "\n", encoding="utf-8")
started = monotonic()
data = report(output / "snapshot", identifier, statistics, settings)
report_seconds = monotonic() - started
(output / "report.json").write_text(canonical(data) + "\n", encoding="utf-8")
(output / "report.md").write_text(markdown(data), encoding="utf-8")
metrics = {
    "code_version": data["code_version"],
    "aggregate_code_version": data["aggregate_code_version"],
    "correction_rate": cell(statistics)["quality"]["correction_rate"],
    "no_information_rate": cell(statistics)["quality"]["no_information_rate"],
    "attribute_unknown_rates": cell(statistics)["quality"]["attribute_unknown_rates"],
    "synthetic_only": True, "python": platform.python_version(), "platform": platform.system(),
    "duckdb": duckdb.__version__, "snapshot_id": identifier,
    "asset_rows": data["overall"]["asset_rows"],
    "sha_distinct": data["overall"]["sha_distinct"],
    "duplicate_rows": data["overall"]["duplicate_rows"],
    "subjects": cell(statistics)["subject_count"],
    "subject_n_eff": cell(statistics)["effective_sample_size"],
    "max_weight": cell(statistics)["quality"]["max_weight"],
    "rule_stat_rows": len(statistics["rows"]),
    "support_statuses": dict(Counter(r["quality"]["status"] for r in statistics["rows"])),
    "aggregate_seconds": round(aggregate_seconds, 6), "report_seconds": round(report_seconds, 6),
    "snapshot_parquet_bytes": data["processing"]["snapshot_bytes"],
    "json_bytes": (output / "report.json").stat().st_size,
    "markdown_bytes": (output / "report.md").stat().st_size,
    "m3_checks": data["m3_checks"],
}
(output / "fixture-metrics.json").write_text(
    json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
)
print(json.dumps(metrics, ensure_ascii=False))
