from itertools import combinations
from pathlib import Path

from colorstats.schema.taxonomy import load_taxonomy
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
    terrain = load_taxonomy(Path("taxonomy"))["terrain"]["labels"] + ["tree"]
    domain_pairs = [r for r in detailed["rows"] if r["scope"] == "condition"
                    and r["conditions"] == {"domain": "real_terrain"} and r["kind"] == "relation"]
    assert {tuple(r["parts"]) for r in domain_pairs} == set(combinations(sorted(terrain), 2))
    assert detailed["terrain_relation_rows"] > 0
    sand_snow = next(r for r in domain_pairs if r["parts"] == ["sand", "snow_ice"])
    assert sand_snow["subject_count"] == 0
    assert sand_snow["subject_deficit_30"] == 30
    assert "部位不足" in sand_snow["causes"]
    assert len(detailed["rows"]) == len({(r["scope"], r["stratum"], str(r["conditions"]),
                                        r["kind"], tuple(r["parts"])) for r in detailed["rows"]})


def test_collection_focus_parts_exist_in_taxonomy():
    from colorstats.collect.targets import load_targets

    documents = load_taxonomy(Path("taxonomy"))
    groups = documents["parts"]["groups"]
    valid = {"real_building": {*groups, *(p for parts in groups.values() for p in parts)},
             "real_terrain": {"tree", *documents["terrain"]["labels"]}}
    config = load_targets(Path("configs/collection_targets.yaml"))
    for layer in config["strata"]:
        assert set(layer["focus_parts"]) <= valid[layer["attributes"]["domain"]]
