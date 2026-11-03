import hashlib
import json
import math
from pathlib import Path

import duckdb
import pytest

from colorstats.stats import distributions, weights
from colorstats.stats.aggregate import aggregate, config_hash
from colorstats.stats.aggregate_cli import load_settings, main
from colorstats.stats.snapshot import TABLES, canonical, digest

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "real_building"


@pytest.fixture
def settings():
    result = load_settings(ROOT / "configs/stats.yaml",
                           ROOT / "configs/collection_targets.yaml", ROOT / "taxonomy")
    result["strata"] = [
        {"id": "a", "subjects": 100, "attributes": {
            "domain": DOMAIN, "style": "gothic", "building_type": "temple",
        }},
        {"id": "b", "subjects": 100, "attributes": {
            "domain": DOMAIN, "style": "modern", "building_type": "house",
        }},
        {"id": "t", "subjects": 100, "attributes": {
            "domain": "real_terrain", "biome_like": "forest",
        }},
    ]
    return result


def snapshot(root, subjects=40, *, unknown=0, split=None, duplicates=False,
             reverse=False, input_runs=(), zero=False, invalid=False, multi=False, terrain=False):
    root.mkdir()
    quality = {
        "supported_by_domain": {DOMAIN: ["door"], "real_terrain": []},
        "group_members": {DOMAIN + "/wall": ["wall_main"],
                          "real_terrain/tree": ["vegetation_tree_canopy", "tree_trunk"]},
    }
    with duckdb.connect() as db:
        for table, schema in TABLES.items():
            db.execute(f"CREATE TABLE {table} ({schema})")
        for i in range(subjects + unknown):
            domain = "real_terrain" if terrain else DOMAIN
            aid = f"asset-{i:04d}"
            sid = f"subject-{i:04d}" if i < subjects else None
            second = split is not None and i >= split
            attrs = ({"style": "modern", "building_type": "house"} if second else {
                "style": "gothic", "building_type": "temple",
            })
            if terrain:
                attrs = {"biome_like": "forest"}
            data = {
                "scene_attributes": attrs, "quality": {}, "subject": {"scene_attributes": {}},
                "selection": {r["stage"] + "_run_id": r["id"] for r in input_runs},
            }
            db.execute("INSERT INTO assets VALUES (?,?,?,?,?,?,?,?)", [
                aid, f"sha-{i:04d}", domain, sid, aid, True, "[]", canonical(data),
            ])
            color = [.8 if second else .2, -.1, .001 if i % 2 else -.001]
            door = [.5, .1, -.001 if i % 2 else .001]
            rid = ("z" if reverse else "a") + aid
            gid = ("a" if reverse else "z") + aid
            area = 0 if zero else .2
            db.execute("INSERT INTO regions VALUES (?,?,?,?,?)", [
                rid, aid, "color", "tree_trunk" if terrain else "door",
                canonical({"area_ratio": area}),
            ])
            # 同一役割の複数クラスタは最大クラスタだけを点観測にする。
            for j, (value, fraction) in enumerate(((door, .7), ([.99, 0, 0], .3))):
                db.execute("INSERT INTO observations VALUES (?,?,?,?,?,?,?)", [
                    f"obs{j}-{aid}", aid, rid, "color", not terrain, "[]",
                    canonical({"observed_oklab": {"dominant": value}, "area_ratio": fraction}),
                ])
            db.execute("INSERT INTO groups VALUES (?,?,?,?,?,?)", [
                gid, aid, "color", domain + ("/tree" if terrain else "/wall"), True,
                canonical({"observations": [{"observed_oklab": {"dominant": color}}],
                           "area_ratio": .6}),
            ])
            db.execute("INSERT INTO regions VALUES (?,?,?,?,?)", [
                "unsupported-" + aid, aid, "color", "tree_trunk" if terrain else "wall_main",
                canonical({"area_ratio": .6}),
            ])
            if multi:
                db.execute("INSERT INTO regions VALUES (?,?,?,?,?)", [
                    "extra-" + aid, aid, "color", "door", canonical({"area_ratio": .1}),
                ])
                db.execute("INSERT INTO observations VALUES (?,?,?,?,?,?,?)", [
                    "extra-obs-" + aid, aid, "extra-" + aid, "color", True, "[]",
                    canonical({"observed_oklab": {"dominant": [.9, .1, 0]}, "area_ratio": 1}),
                ])
            if duplicates:
                db.execute("INSERT INTO assets VALUES (?,?,?,?,?,?,?,?)", [
                    "dup-" + aid, f"sha-{i:04d}", domain, sid, aid, False,
                    '["sha_duplicate"]', canonical(data),
                ])
            if invalid:
                db.execute("INSERT INTO relations VALUES (?,?,?,?,?,?)", [
                    "bad-" + aid, aid, "color", True, "[]",
                    canonical({"region_a": rid, "region_b": gid, "type": "co_occurs",
                               "delta_l": 1, "delta_c": 1, "delta_h": None,
                               "delta_e_ok": 1, "area_ratio": 0}),
                ])
        for row in input_runs:
            db.execute("INSERT INTO runs VALUES (?,?,?)", [
                row["id"], row["stage"], canonical(row["data"]),
            ])
        manifest = {"format_version": 1, "gate_version": "D15-v1",
                    "taxonomy_version": "0.1.0", "quality": quality, "files": {},
                    "exclusions": {"sha_duplicate": subjects if duplicates else 0}}
        for table in TABLES:
            path = root / (table + ".parquet")
            db.execute(f"COPY (SELECT * FROM {table} ORDER BY ALL) TO ? (FORMAT PARQUET)",
                       [str(path)])
            manifest["files"][path.name] = {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "rows": db.execute(f"SELECT count(*) FROM {table}").fetchone()[0],
            }
    manifest["snapshot_id"] = digest(manifest)
    (root / "manifest.json").write_text(canonical(manifest), encoding="utf-8")
    return manifest["snapshot_id"]


def cell(result, parts=("wall",), condition=None, kind="palette"):
    return next(row for row in result["rows"]
                if row["target_parts"] == list(parts)
                and row["conditions"] == (condition or {"domain": DOMAIN})
                and row["distribution"]["kind"] == kind)


def point(subject, image, layer, value=0., area=1.):
    return {"subject": subject, "sha256": image, "stratum": layer,
            "area": area, "metrics": {"L": value, "a": 0., "b": 0.}}


def test_weights_hand_calculation_and_image_normalization(settings):
    rows = [point("s1", "i1", "a", area=.25), point("s1", "i1", "a", area=.75),
            point("s1", "i2", "a"), point("s2", "i3", "b"), point("s3", "i4", "b")]
    values, support = weights.calculate(rows, settings["strata"], {"domain": DOMAIN})
    assert values == pytest.approx([.1875, .5625, .75, .75, .75])
    assert support["weight"] == 3
    assert support["effective_sample_size"] == pytest.approx(8 / 3)
    assert support["sample_count"] == 4
    assert support["subject_count"] == 3
    assert support["missing_target_mass"] == 0


def test_missing_zero_unknown_unassigned_and_high_weight(settings):
    rows = [point(str(i), str(i), "a") for i in range(12)]
    rows += [point("last", "last", "b"), point(None, "unknown", None),
             point("unassigned", "unassigned", None)]
    values, support = weights.calculate(rows, settings["strata"], {"domain": DOMAIN})
    assert support["max_weight"] == 6.5
    assert values[-2:] == [0, 0]
    assert support["unknown_images"] == support["unassigned_subjects"] == 1
    assert weights.calculate(rows[:12], settings["strata"], {"domain": DOMAIN})[1][
        "missing_target_mass"] == .5
    empty = weights.calculate([], settings["strata"], {"domain": DOMAIN})[1]
    assert empty["missing_target_mass"] == 1
    capped, _ = weights.calculate(rows, settings["strata"], {"domain": DOMAIN}, cap=5)
    assert capped[12] == 5


def test_subject_stratum_conflicts_and_search_intent(settings):
    assets = {
        str(i): {"eligible": True, "subject_id": "s", "domain": DOMAIN, "data": {
            "scene_attributes": attrs, "subject": {"scene_attributes": {}},
            "search_parameters": {"collection_bias": {"stratum": "a"}},
        }} for i, attrs in enumerate(({"style": "gothic", "building_type": "temple"},
                                     {"style": "modern", "building_type": "house"}))
    }
    assert weights.assign_strata(assets, settings["strata"])[0] == {"s": None}
    assets["0"]["data"]["scene_attributes"] = {}
    del assets["1"]
    assert weights.assign_strata(assets, settings["strata"])[0] == {"s": None}


def test_inverse_cdf_and_mixture_and_circular_boundary():
    child = distributions.summarize([point("a", "a", "a", 0)], [1], "palette")
    parent = distributions.summarize([point("b", "b", "b", 10)], [1], "palette")
    mixed = distributions.mix(child, parent, .5)
    assert [r["value"] for r in mixed["quantiles"]["L"]] == [0, 0, 0, 10, 10]
    assert mixed["cdf"]["L"] == [[0, .5], [10, .5]]
    rows = [{"metrics": {"delta_l": 0, "delta_c": 0, "delta_e_ok": 1, "area_ratio": 1,
                         "delta_h": h}} for h in (179, -179, 180, None)]
    hue = distributions.summarize(rows, [.25] * 4, "relation")["hue"]
    assert hue["bins"][0] == .5 and hue["bins"][-1] == .25
    assert hue["null_mass"] == .25
    assert math.fsum(hue["bins"]) + hue["null_mass"] == 1


def test_snapshot_determinism_duplication_support_and_pair(tmp_path, settings):
    a = aggregate(tmp_path / "a", snapshot(tmp_path / "a"), settings)
    b = aggregate(tmp_path / "b", snapshot(tmp_path / "b", duplicates=True, reverse=True), settings)
    for parts, kind in ((("wall",), "palette"), (("wall", "door"), "relation")):
        first, second = cell(a, parts, kind=kind), cell(b, parts, kind=kind)
        assert first["quality"]["status"] == "direct"
        assert first["subject_count"] == first["effective_sample_size"] == 40
        assert first["sample_count"] == 40
        assert first["distribution"] == second["distribution"]
    relation = cell(a, ("wall", "door"), kind="relation")["distribution"]
    assert relation["quantiles"]["delta_l"][2]["value"] == pytest.approx(.3)
    assert relation["quantiles"]["area_ratio"][2]["value"] == pytest.approx(1 / 3)
    assert "delta_h" not in relation["quantiles"]
    assert cell(a, ("wall_main",))["quality"]["status"] == "unsupported"
    assert "model_unvalidated" in cell(a, ("wall_main",))["quality"]["flags"]
    assert cell(a, ("tree",), {"domain": "real_terrain"})["quality"]["status"] == "unsupported"
    assert a == aggregate(tmp_path / "a", a["snapshot_id"], settings)


@pytest.mark.parametrize(("count", "status"), [(0, "unsupported"), (9, "unsupported"),
                                              (10, "unsupported"), (29, "unsupported"),
                                              (30, "direct")])
def test_root_support_boundaries(tmp_path, settings, count, status):
    result = aggregate(tmp_path / "input", snapshot(tmp_path / "input", count), settings)
    row = cell(result)
    assert row["quality"]["status"] == status
    assert row["subject_count"] == row["effective_sample_size"] == count
    assert row["confidence_interval"] is None


def test_child_cdf_smoothing_and_borrowed_counts(tmp_path, settings):
    result = aggregate(tmp_path / "input",
                       snapshot(tmp_path / "input", 40, split=10), settings)
    parent = cell(result)
    child = cell(result, condition={"domain": DOMAIN, "style": "gothic", "building_type": "temple"})
    assert parent["quality"]["status"] == "direct"
    assert child["quality"]["status"] == "smoothed"
    assert child["quality"]["lambda"] == pytest.approx(1 / 3)
    assert child["subject_count"] == child["effective_sample_size"] == 10
    assert child["distribution"]["cdf"]["L"][0] == pytest.approx([.2, 7 / 9])
    assert child["distribution"]["cdf"]["L"][1] == pytest.approx([.8, 2 / 9])
    low = aggregate(tmp_path / "low", snapshot(tmp_path / "low", 60, split=9), settings)
    borrowed = cell(low, condition={"domain": DOMAIN, "style": "gothic"})
    assert borrowed["quality"]["status"] == "smoothed"
    assert borrowed["quality"]["lambda"] == 0
    assert borrowed["subject_count"] == 9
    assert borrowed["distribution"]["cdf"] == cell(low)["distribution"]["cdf"]


def test_unknown_diagnostic_zero_area_and_tampering(tmp_path, settings):
    root = tmp_path / "input"
    identifier = snapshot(root, 0, unknown=2, zero=True)
    result = aggregate(root, identifier, settings)
    assert all(row["subject_count"] == 0 for row in result["rows"])
    root2 = tmp_path / "unknown"
    result = aggregate(root2, snapshot(root2, 30, unknown=2), settings)
    row = cell(result)
    assert row["subject_count"] == 30 and row["quality"]["unknown_images"] == 2
    assert row["distribution"]["diagnostics"]["unknown_only"]["cdf"]["L"] == [[.2, 1.]]
    (root2 / "groups.parquet").write_bytes(b"broken")
    with pytest.raises(ValueError, match="hash"):
        aggregate(root2, result["snapshot_id"], settings)


def test_cli_offline_and_hash_key(tmp_path, settings, monkeypatch):
    root = tmp_path / "input"
    identifier = snapshot(root, 30)
    output = tmp_path / "output.json"
    monkeypatch.setattr("colorstats.stats.aggregate_cli.load_settings", lambda *args: settings)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("sys.argv", [
        "aggregate", "--snapshot", str(root), "--snapshot-id", identifier,
                                    "--output", str(output), "--dry-run"])
    assert main() == 0
    assert json.loads(output.read_text(encoding="utf-8"))["snapshot_id"] == identifier
    assert main() == 1
    payload = {"snapshot_id": identifier, "settings": settings,
               "snapshot": "one", "output_path": "one"}
    assert config_hash(payload) == config_hash(payload | {"snapshot": "two", "output_path": "two"})
    assert config_hash(payload) != config_hash(payload | {"snapshot_id": "other"})


def test_multiple_regions_pairs_and_domain_separation(tmp_path, settings):
    multi = tmp_path / "multi"
    result = aggregate(multi, snapshot(multi, 30, multi=True, invalid=True), settings)
    door = cell(result, ("door",))
    relation = cell(result, ("wall", "door"), kind="relation")
    assert door["subject_count"] == door["sample_count"] == door["effective_sample_size"] == 30
    assert door["distribution"]["cdf"]["L"][0] == pytest.approx([.5, 2 / 3])
    assert relation["distribution"]["cdf"]["delta_l"][0] == pytest.approx([.3, 2 / 3])
    assert relation["distribution"]["cdf"]["delta_l"][1] == pytest.approx([.7, 1 / 3])
    terrain = tmp_path / "terrain"
    result = aggregate(terrain, snapshot(terrain, 30, terrain=True), settings)
    assert cell(result, ("tree",), {"domain": "real_terrain"})["quality"]["status"] == "direct"
    assert cell(result)["subject_count"] == 0
    assert cell(result)["quality"]["status"] == "unsupported"


def test_effective_support_below_count_boundary(tmp_path, settings):
    root = tmp_path / "concentrated"
    result = aggregate(root, snapshot(root, 40, split=9), settings)
    row = cell(result)
    assert row["subject_count"] == 40
    assert row["effective_sample_size"] == pytest.approx(27.9)
    assert row["quality"]["status"] == "unsupported"
