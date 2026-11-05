from colorstats.stats.aggregate import aggregate
from colorstats.stats.deficits import deficits
from colorstats.stats.report import report
from tests.test_stats_aggregate import settings as settings
from tests.test_stats_aggregate import snapshot


def test_fixed_report_thresholds_and_unvalidated_parts(tmp_path, settings):
    root = tmp_path / "snapshot"
    identifier = snapshot(root, 2)
    stats = aggregate(root, identifier, settings)
    data = report(root, identifier, stats, settings)
    result = deficits(data)
    assert result == deficits(data)
    assert result["snapshot_id"] == identifier
    condition = next(r for r in result["rows"] if r["scope"] == "condition"
                     and r["parts"] == ["wall"] and r["conditions"] == {"domain": "real_building"})
    assert condition["subject_deficit_10"] == 8
    assert condition["subject_deficit_30"] == 28
    assert condition["n_eff_deficit_30"] == 28
    assert "subject不足" in condition["causes"]
    assert result["cause_counts_overlapping"]["subject不足"] > 0
    detailed = deficits(data, snapshot=root, settings=settings)
    relations = [r for r in detailed["rows"]
                 if r["scope"] == "stratum" and r["kind"] == "relation"]
    assert relations
    assert all(r["subject_deficit_30"] == max(0, 30 - r["subject_count"]) for r in relations)
