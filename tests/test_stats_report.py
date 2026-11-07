import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

from colorstats.stats.aggregate import aggregate
from colorstats.stats.aggregate_cli import load_settings
from colorstats.stats.report import markdown, report
from colorstats.stats.snapshot import TABLES, canonical, digest
from tests.test_stats_aggregate import DOMAIN, cell, snapshot
from tests.test_stats_aggregate import settings as settings

ROOT = Path(__file__).resolve().parents[1]


def revise(root, change):
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    with duckdb.connect() as db:
        for table in TABLES:
            db.execute(
                f"CREATE TABLE {table} AS SELECT * FROM read_parquet(?)",
                [str(root / (table + ".parquet"))],
            )
        change(db, manifest)
        for table in TABLES:
            path = root / (table + ".parquet")
            db.execute(
                f"COPY (SELECT * FROM {table} ORDER BY ALL) TO ? (FORMAT PARQUET)", [str(path)]
            )
            manifest["files"][path.name] = {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "rows": db.execute(f"SELECT count(*) FROM {table}").fetchone()[0],
            }
    manifest.pop("snapshot_id")
    manifest["snapshot_id"] = digest(manifest)
    (root / "manifest.json").write_text(canonical(manifest), encoding="utf-8")
    return manifest["snapshot_id"]


def test_all_twelve_strata_duplicates_rates_and_exclusions(tmp_path):
    settings = load_settings(
        ROOT / "configs/stats.yaml", ROOT / "configs/collection_targets.yaml", ROOT / "taxonomy"
    )
    root = tmp_path / "snapshot"
    snapshot(root, 2, duplicates=True)

    def change(db, manifest):
        for aid, data_json in db.execute("SELECT id, data FROM assets").fetchall():
            data = json.loads(data_json)
            attrs = settings["strata"][1]["attributes"]
            data["scene_attributes"] = {k: v for k, v in attrs.items() if k != "domain"}
            data["search_parameters"] = {"collection_bias": {"intended_attributes": attrs}}
            data["quality"] = {"author": " A ", "license": "CC0"}
            db.execute("UPDATE assets SET data=? WHERE id=?", [canonical(data), aid])
        db.execute(
            "UPDATE assets SET eligible=false, reasons=? WHERE id='asset-0001'",
            ['["license_conditions","license_not_allowed"]'],
        )
        db.execute("UPDATE observations SET eligible=false WHERE asset_id='asset-0001'")
        db.execute("UPDATE groups SET eligible=false WHERE asset_id='asset-0001'")

    identifier = revise(root, change)
    stats = aggregate(root, identifier, settings)
    data = report(root, identifier, stats, settings)
    assert len(data["strata"]) == 12
    overall = data["overall"]
    assert (overall["asset_rows"], overall["sha_distinct"], overall["duplicate_rows"]) == (4, 2, 2)
    assert overall["eligible"] == {"numerator": 1, "denominator": 4, "value": 0.25}
    assert overall["rights_eligible"]["numerator"] == 3
    assert overall["exclusions"]["license_conditions"]["denominator"] == 4
    assert overall["exclusions"]["license_not_allowed"]["numerator"] == 1
    assert overall["confirmed_subjects_before"] == 2
    assert overall["confirmed_subjects_after"] == 1
    layer = data["strata"][1]["inferred"]
    assert layer == overall | {"subject_deficit": 299, "subject_coverage": 1 / 300}
    empty = data["strata"][0]["inferred"]
    assert empty["asset_rows"] == 0 and empty["eligible"]["value"] is None
    assert empty["subject_deficit"] == 300
    assert layer["concentration"]["author"]["top_share"]["value"] == 1
    assert not data["scale_target"]["achieved"] and not data["m3_complete"]
    rendered = markdown(data)
    assert identifier in rendered and "license_conditions: 1/4" in rendered
    assert "条件1: unverified" in rendered and "条件4: failed" in rendered


def test_unclassified_candidates_intent_conflicts_and_overlap(tmp_path, settings):
    root = tmp_path / "snapshot"
    snapshot(root, 3, unknown=2)

    def change(db, manifest):
        for aid, data_json in db.execute("SELECT id, data FROM assets").fetchall():
            data = json.loads(data_json)
            data["search_parameters"] = {
                "collection_bias": {
                    "intended_attributes": {
                        "domain": DOMAIN,
                        "style": "modern",
                        "building_type": "house",
                    },
                }
            }
            if aid == "asset-0000":
                data["scene_attributes"] = {}
            if aid == "asset-0001":
                data["subject"]["scene_attributes"] = {"style": "modern"}
            if aid == "asset-0003":
                data["candidates"] = [{"subject_id": "candidate"}]
            data["quality"] = {
                "scene_inference": {
                    "attributes": {
                        "style": {"state": "unknown" if aid == "asset-0000" else "inferred"},
                    }
                }
            }
            db.execute("UPDATE assets SET data=? WHERE id=?", [canonical(data), aid])

    identifier = revise(root, change)
    # 包含する目標層でも未割当を負数にせず、画像集合の和集合で数える。
    settings["strata"].append(
        {"id": "overlap", "subjects": 100, "attributes": {"domain": DOMAIN, "style": "gothic"}}
    )
    data = report(root, identifier, aggregate(root, identifier, settings), settings)
    assert data["classification"]["attributes_missing"]["numerator"] == 1
    assert data["classification"]["attributes_conflict"]["numerator"] == 1
    assert data["classification"]["intent_mismatch"]["numerator"] == 4
    assert data["classification"]["multiple_strata"]["numerator"] == 1
    assert data["classification"]["image_unassigned"]["numerator"] == 0
    assert data["classification"]["unassigned"]["numerator"] == 3
    assert data["overall"]["candidate_only_images"]["numerator"] == 1
    assert data["overall"]["unknown_subject_images"]["numerator"] == 1
    assert data["strata"][1]["intended"]["asset_rows"] == 5
    comparison = data["strata"][1]["intent_comparison"]
    assert comparison["attributes_missing"]["numerator"] == 1
    assert comparison["mismatch"] == {"numerator": 4, "denominator": 5, "value": 0.8}
    assert data["strata"][1]["inferred"]["asset_rows"] == 1
    assert data["classification"]["attribute_states"]["style"] == {"inferred": 4, "unknown": 1}


@pytest.mark.parametrize(
    ("subjects", "split", "expected", "effective"),
    [
        (9, None, False, 9),
        (10, None, True, 10),
        (10, 9, False, 3.6),
        (40, 9, True, 27.9),
    ],
)
def test_raw_gate_and_neff_match_aggregate(
    tmp_path, settings, subjects, split, expected, effective
):
    root = tmp_path / "snapshot"
    identifier = snapshot(root, subjects, split=split)
    stats = aggregate(root, identifier, settings)
    data = report(root, identifier, stats, settings)
    wall = next(
        r
        for r in data["support"]
        if r["conditions"] == {"domain": DOMAIN} and r["target_parts"] == ["wall"]
    )
    assert wall["effective_sample_size"] == pytest.approx(effective)
    assert wall["quality"] == cell(stats)["quality"]
    assert data["usefulness_gates"][DOMAIN]["passed"] is expected
    assert not data["usefulness_gates"]["real_terrain"]["passed"]


def test_single_subject_does_not_pass_from_many_images(tmp_path, settings):
    root = tmp_path / "snapshot"
    snapshot(root, 30)
    identifier = revise(
        root, lambda db, m: db.execute("UPDATE assets SET subject_id='only-subject'")
    )
    data = report(root, identifier, aggregate(root, identifier, settings), settings)
    assert data["overall"]["concentration"]["subject"]["top_share"]["value"] == 1
    assert all(r["effective_sample_size"] <= 1 for r in data["support"])
    assert not data["usefulness_gates"][DOMAIN]["passed"]


@pytest.mark.parametrize("unknown_attributes", [False, True])
def test_both_domains_pass_without_claiming_full_m3(tmp_path, settings, unknown_attributes):
    root = tmp_path / "snapshot"
    snapshot(root, 20)

    def change(db, manifest):
        for aid, raw in db.execute("SELECT id, data FROM assets ORDER BY id LIMIT 10").fetchall():
            data = json.loads(raw)
            data["scene_attributes"] = {"biome_like": "forest"}
            db.execute(
                "UPDATE assets SET domain='real_terrain', data=? WHERE id=?", [canonical(data), aid]
            )
            db.execute("UPDATE groups SET role='real_terrain/tree' WHERE asset_id=?", [aid])
            db.execute("UPDATE observations SET eligible=false WHERE asset_id=?", [aid])
            db.execute("UPDATE regions SET label='tree_trunk' WHERE asset_id=?", [aid])
        if unknown_attributes:
            for aid, raw in db.execute("SELECT id, data FROM assets").fetchall():
                data = json.loads(raw)
                data["scene_attributes"] = {"style": "unknown", "biome_like": None}
                db.execute("UPDATE assets SET data=? WHERE id=?", [canonical(data), aid])

    identifier = revise(root, change)
    data = report(root, identifier, aggregate(root, identifier, settings), settings)
    assert all(g["passed"] for g in data["usefulness_gates"].values())
    assert data["m3_checks"][3]["status"] == "passed"
    assert "passed は層補正の有効性を意味しない" in data["m3_checks"][3]["reason"]
    assert data["m3_checks"][3]["role_results"] == {
        domain: gate["correction"] for domain, gate in data["usefulness_gates"].items()
    }
    if unknown_attributes:
        for gate in data["usefulness_gates"].values():
            for diagnostic in gate["correction"]:
                if diagnostic["subject_count"]:
                    assert diagnostic["no_information_rate"] == 1
                    assert diagnostic["correction_rate"] == 0
                    assert "weak_correction" in diagnostic["quality_flags"]
                    assert all(rate == 1 for rate in diagnostic["attribute_unknown_rates"].values())
        assert "補正率" in markdown(data) and "情報なし割合" in markdown(data)
        assert "weak_correction" in markdown(data)
        assert "passed は層補正の有効性を意味しない" in markdown(data)
    assert [c["status"] for c in data["m3_checks"]] == [
        "unverified",
        "unverified",
        "passed",
        "passed",
        "passed",
        "unverified",
    ]
    assert not data["m3_complete"]


@pytest.mark.parametrize("alter", ["snapshot", "statistics", "settings", "artifact"])
def test_mixed_or_modified_inputs_are_rejected(tmp_path, settings, alter):
    root = tmp_path / "snapshot"
    identifier = snapshot(root, 1)
    stats = aggregate(root, identifier, settings)
    if alter == "snapshot":
        stats["snapshot_id"] = "another"
    elif alter == "statistics":
        stats["rows"][0]["effective_sample_size"] += 1
    elif alter == "settings":
        settings = copy.deepcopy(settings)
        settings["strata"][0]["subjects"] += 1
    else:
        (root / "assets.parquet").write_bytes(b"tampered")
    with pytest.raises(ValueError):
        report(root, identifier, stats, settings)


def test_installed_cli_reproduces_and_preserves_existing_output(tmp_path):
    settings = load_settings(
        ROOT / "configs/stats.yaml", ROOT / "configs/collection_targets.yaml", ROOT / "taxonomy"
    )
    root = tmp_path / "snapshot"
    identifier = snapshot(root, 1)
    statistics = tmp_path / "statistics.json"
    statistics.write_text(canonical(aggregate(root, identifier, settings)), encoding="utf-8")
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.pop("PYTHONPATH", None)
    command = [
        sys.executable,
        "-m",
        "colorstats.stats.report_cli",
        "--snapshot",
        str(root),
        "--snapshot-id",
        identifier,
        "--statistics",
        str(statistics),
        "--config",
        str(ROOT / "configs/stats.yaml"),
        "--targets",
        str(ROOT / "configs/collection_targets.yaml"),
        "--taxonomy",
        str(ROOT / "taxonomy"),
    ]
    first = tmp_path / "first"
    second = tmp_path / "second"
    for output in (first, second):
        result = subprocess.run(
            command + ["--output", str(output)],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
    assert (first / "report.json").read_bytes() == (second / "report.json").read_bytes()
    assert (first / "report.md").read_bytes() == (second / "report.md").read_bytes()
    before = (first / "report.json").read_bytes()
    assert (
        subprocess.run(
            command + ["--output", str(first)], cwd=tmp_path, env=env, capture_output=True
        ).returncode
        == 1
    )
    assert (first / "report.json").read_bytes() == before


def test_shared_sha_is_counted_once_globally_not_per_stratum_sum(tmp_path, settings):
    root = tmp_path / "snapshot"
    snapshot(root, 2, duplicates=True)

    def change(db, manifest):
        data = json.loads(
            db.execute("SELECT data FROM assets WHERE id='dup-asset-0000'").fetchone()[0]
        )
        data["scene_attributes"] = {"style": "modern", "building_type": "house"}
        db.execute("UPDATE assets SET data=? WHERE id='dup-asset-0000'", [canonical(data)])

    identifier = revise(root, change)
    data = report(root, identifier, aggregate(root, identifier, settings), settings)
    assert data["overall"]["sha_distinct"] == 2
    assert [s["inferred"]["sha_distinct"] for s in data["strata"]] == [2, 1, 0]
    assert data["overall"]["duplicate_rows"] == 2
    assert data["strata"][0]["inferred"]["duplicate_rows"] == 1
    assert data["strata"][1]["inferred"]["duplicate_rows"] == 0


def test_subject_location_and_era_use_collection_attribute_reader(tmp_path):
    settings = load_settings(ROOT / "configs/stats.yaml",
                             ROOT / "configs/collection_targets.yaml", ROOT / "taxonomy")
    root = tmp_path / "snapshot"
    snapshot(root, 1)

    def change(db, manifest):
        data = json.loads(db.execute("SELECT data FROM assets").fetchone()[0])
        data["subject"] = {"scene_attributes": {}, "location": "europe", "era": "medieval"}
        db.execute("UPDATE assets SET data=?", [canonical(data)])

    identifier = revise(root, change)
    data = report(root, identifier, aggregate(root, identifier, settings), settings)
    layer = next(row for row in data["strata"] if row["id"] == "gothic-temple")["inferred"]
    assert layer["asset_rows"] == layer["confirmed_subjects_after"] == 1
    assert layer["subject_deficit"] == 299
    assert data["classification"]["attributes_missing"]["numerator"] == 0
    assert data["classification"]["attribute_states"]["region"] == {"recorded": 1}
    assert data["classification"]["attribute_states"]["era"] == {"recorded": 1}


def test_subject_attribute_evidence_states_are_retained(tmp_path):
    settings = load_settings(ROOT / "configs/stats.yaml",
                             ROOT / "configs/collection_targets.yaml", ROOT / "taxonomy")
    root = tmp_path / "snapshot"
    snapshot(root, 1)

    def change(db, manifest):
        raw = json.loads(db.execute("SELECT data FROM assets").fetchone()[0])
        raw["subject"].update({
            "location": "europe", "era": "medieval",
            "attribute_evidence": {"attributes": {
                "region": {"state": "inferred", "value": "europe"},
                "era": {"state": "preserved", "value": "medieval"},
            }},
        })
        db.execute("UPDATE assets SET data=?", [canonical(raw)])

    identifier = revise(root, change)
    data = report(root, identifier, aggregate(root, identifier, settings), settings)
    assert data["classification"]["attribute_states"]["region"] == {"inferred": 1}
    assert data["classification"]["attribute_states"]["era"] == {"preserved": 1}


@pytest.mark.parametrize(("state", "value", "expected"), [
    ("conflict", None, "conflict"),
    ("conflict", "", "conflict"),
    ("conflict", "unknown", "conflict"),
    ("conflict", "gothic", "conflict"),
    ("inferred", None, "unknown"),
    ("unknown", None, "unknown"),
    (None, None, "unknown"),
    (None, "gothic", "recorded"),
])
def test_saved_conflict_is_not_replaced_by_unknown(tmp_path, settings, state, value, expected):
    root = tmp_path / "snapshot"
    snapshot(root, 1)

    def change(db, manifest):
        raw = json.loads(db.execute("SELECT data FROM assets").fetchone()[0])
        raw["scene_attributes"] = {"style": value}
        raw["quality"] = {"scene_inference": {"attributes": {"style": {"state": state}}}}
        db.execute("UPDATE assets SET data=?", [canonical(raw)])

    identifier = revise(root, change)
    data = report(root, identifier, aggregate(root, identifier, settings), settings)
    assert data["classification"]["attribute_states"]["style"] == {expected: 1}
    assert f'"style":{{"{expected}":1}}' in markdown(data)


@pytest.mark.parametrize("exclude_conflicting_image", [False, True])
def test_subject_stratum_conflict_changes_adopted_support_and_deficits(
    tmp_path, settings, exclude_conflicting_image,
):
    root = tmp_path / "snapshot"
    snapshot(root, 2, split=1)

    def change(db, manifest):
        db.execute("UPDATE assets SET subject_id='same-subject'")
        if exclude_conflicting_image:
            db.execute("UPDATE assets SET eligible=false, reasons=? WHERE id='asset-0001'",
                       ['["license_conditions"]'])
            for table in ("observations", "groups"):
                db.execute(f"UPDATE {table} SET eligible=false WHERE asset_id='asset-0001'")

    identifier = revise(root, change)
    stats = aggregate(root, identifier, settings)
    data = report(root, identifier, stats, settings)
    a, b = (row["inferred"] for row in data["strata"][:2])
    assert a["asset_rows"] == b["asset_rows"] == 1
    assert b["confirmed_subjects_after"] == 0
    assert b["subject_deficit"] == 100
    if exclude_conflicting_image:
        assert a["confirmed_subjects_after"] == cell(stats)["subject_count"] == 1
        assert a["subject_deficit"] == 99
        assert data["classification"]["subject_stratum_conflict"]["numerator"] == 0
    else:
        assert a["confirmed_subjects_after_snapshot"] == b["confirmed_subjects_after_snapshot"] == 1
        assert a["confirmed_subjects_after"] == cell(stats)["subject_count"] == 0
        assert a["subject_deficit"] == 100
        assert data["classification"]["image_unassigned"]["numerator"] == 0
        assert data["classification"]["unassigned"] == {
            "numerator": 2, "denominator": 2, "value": 1,
        }
        assert data["classification"]["subject_stratum_conflict"]["numerator"] == 2
        assert data["classification"]["unassigned_subject_reasons"] == {
            "subject_stratum_conflict": 1,
        }


@pytest.mark.parametrize(("terrain", "role", "union", "stratum"), [
    (False, "wall_main", "wall", "a"), (True, "tree_trunk", "tree", "t"),
])
@pytest.mark.parametrize("missing_union", [False, True])
def test_role_specific_d15_losses_and_incomplete_union_evidence(
    tmp_path, settings, terrain, role, union, stratum, missing_union,
):
    root = tmp_path / "snapshot"
    snapshot(root, 2, terrain=terrain)
    domain = "real_terrain" if terrain else DOMAIN

    def change(db, manifest):
        manifest["quality"]["supported_by_domain"][domain].append(role)
        db.execute("UPDATE assets SET eligible=false, reasons=? WHERE id='asset-0000'",
                   ['["license_conditions","license_not_allowed"]'])
        db.execute("DELETE FROM observations WHERE asset_id='asset-0000'")
        if terrain:
            db.execute("DELETE FROM observations WHERE asset_id='asset-0001'")
        db.execute("INSERT INTO observations "
                   "(id,asset_id,region_id,run_id,eligible,reasons,data) VALUES (?,?,?,?,?,?,?)", [
            "rights-excluded", "asset-0000", "unsupported-asset-0000", "color", False, "[]",
            canonical({"observed_oklab": {"dominant": [.5, 0, 0]}, "area_ratio": 1}),
        ])
        db.execute("UPDATE groups SET eligible=false WHERE asset_id='asset-0000'")
        if missing_union:
            db.execute("DELETE FROM groups WHERE asset_id='asset-0000'")

    identifier = revise(root, change)
    data = report(root, identifier, aggregate(root, identifier, settings), settings)
    for scope in ("condition", "stratum"):
        rows = [r for r in data["rights_support"] if r["scope"] == scope
                and r["conditions"] == ({"domain": domain} if scope == "condition" else
                                         next(s["attributes"] for s in settings["strata"]
                                              if s["id"] == stratum))]
        individual = next(r for r in rows if r["role"] == role)
        assert individual["recorded_subjects_before_d15"] == 1
        assert individual["recorded_subjects_after_d15"] == 0
        assert individual["lost_subjects_d15"] == 1
        assert individual["adopted_subjects"] == 0
        assert individual["exclusion_reasons"]["license_conditions"] == 1
        combined = next(r for r in rows if r["role"] == union)
        assert combined["recorded_subjects_after_d15"] == 1
        if missing_union:
            assert combined["recorded_subjects_before_d15"] is None
            assert combined["lost_subjects_d15"] is None
            assert combined["unverified_union_assets"] == 1
        else:
            assert combined["recorded_subjects_before_d15"] == 2
            assert combined["lost_subjects_d15"] == 1
    assert data["m3_checks"][4]["status"] == ("unverified" if missing_union else "passed")
    rendered = markdown(data)
    assert "D15で失ったsubject" in rendered and role in rendered


def test_role_d15_loss_does_not_count_a_subject_retained_by_another_image(tmp_path, settings):
    root = tmp_path / "snapshot"
    snapshot(root, 2)

    def change(db, manifest):
        db.execute("UPDATE assets SET subject_id='same-subject'")
        db.execute("UPDATE assets SET eligible=false, reasons=? WHERE id='asset-0000'",
                   ['["license_conditions"]'])
        for table in ("observations", "groups"):
            db.execute(f"UPDATE {table} SET eligible=false WHERE asset_id='asset-0000'")

    identifier = revise(root, change)
    data = report(root, identifier, aggregate(root, identifier, settings), settings)
    door = next(row for row in data["rights_support"] if row["role"] == "door"
                and row["scope"] == "condition" and row["conditions"] == {"domain": DOMAIN})
    assert door["recorded_subjects_before_d15"] == door["recorded_subjects_after_d15"] == 1
    assert door["lost_subjects_d15"] == 0
    assert door["adopted_subjects"] == 1


def test_known_analysis_failure_is_not_missing_union_evidence(tmp_path, settings):
    root = tmp_path / "snapshot"
    snapshot(root, 2)

    def change(db, manifest):
        db.execute("UPDATE assets SET eligible=false, analysis_available=false, "
                   "reasons='[\"missing_analysis\",\"license_conditions\"]' "
                   "WHERE id='asset-0000'")
        for table in ("observations", "groups"):
            db.execute(f"DELETE FROM {table} WHERE asset_id='asset-0000'")

    identifier = revise(root, change)
    data = report(root, identifier, aggregate(root, identifier, settings), settings)
    assert data["rights_excluded_without_analysis"] == 1
    assert data["unobserved_rights_excluded_assets"] == 0
    assert all(row["complete"] for row in data["rights_support"])
    wall = next(row for row in data["rights_support"] if row["role"] == "wall"
                and row["conditions"] == {"domain": DOMAIN})
    assert wall["recorded_subjects_before_d15"] == 1
    assert data["overall"]["exclusions"]["missing_analysis"]["numerator"] == 1
    assert data["m3_checks"][4]["status"] == "passed"


def test_recorded_zero_area_color_is_not_adopted_role_support(tmp_path, settings):
    root = tmp_path / "snapshot"
    identifier = snapshot(root, 1, zero=True)
    stats = aggregate(root, identifier, settings)
    data = report(root, identifier, stats, settings)
    door = next(row for row in data["rights_support"] if row["role"] == "door"
                and row["scope"] == "condition" and row["conditions"] == {"domain": DOMAIN})
    assert door["recorded_subjects_before_d15"] == 1
    assert door["adopted_subjects"] == cell(stats, ("door",))["subject_count"] == 0


@pytest.mark.parametrize("same_subject", [False, True])
def test_partial_memberships_unknown_mix_and_fractional_deficit(tmp_path, settings, same_subject):
    root = tmp_path / "snapshot"
    snapshot(root, 2)

    def change(db, manifest):
        data = json.loads(db.execute("SELECT data FROM assets WHERE id='asset-0001'").fetchone()[0])
        data["scene_attributes"] = {"style": "unknown", "building_type": ""}
        db.execute("UPDATE assets SET data=? WHERE id='asset-0001'", [canonical(data)])
        if same_subject:
            db.execute("UPDATE assets SET subject_id='same-subject'")

    identifier = revise(root, change)
    stats = aggregate(root, identifier, settings)
    data = report(root, identifier, stats, settings)
    a, b = (row["inferred"] for row in data["strata"][:2])
    assert data["classification"]["unassigned"]["numerator"] == 0
    assert data["classification"]["unassigned_subject_reasons"] == {}
    assert a["subject_mass"] == pytest.approx(1 if same_subject else 1.5)
    assert b["subject_mass"] == pytest.approx(0 if same_subject else .5)
    assert b["unassigned_subjects"] == 0
    assert a["subject_deficit"] == pytest.approx(99 if same_subject else 98.5)
    assert b["subject_deficit"] == pytest.approx(100 if same_subject else 99.5)
    assert a["subject_coverage"] == pytest.approx(a["subject_mass"] / 100)
    summary = data["classification"]["partial_correction"][DOMAIN]
    assert summary["correction_rate"] == (1 if same_subject else .5)
    assert summary["no_information_rate"] == (0 if same_subject else .5)
    assert summary["attribute_unknown_rates"]["style"] == (0 if same_subject else .5)
    wall = next(row for row in data["support"] if row["conditions"] == {"domain": DOMAIN}
                and row["target_parts"] == ["wall"])
    assert wall["quality"] == cell(stats)["quality"]
    assert wall["effective_sample_size"] == pytest.approx(1 if same_subject else 1.8)
    assert wall["correction_rate"] == summary["correction_rate"]


def test_known_values_outside_all_strata_remain_unassigned(tmp_path, settings):
    root = tmp_path / "snapshot"
    snapshot(root, 1)

    def change(db, manifest):
        data = json.loads(db.execute("SELECT data FROM assets").fetchone()[0])
        data["scene_attributes"] = {"style": "outside"}
        db.execute("UPDATE assets SET data=?", [canonical(data)])

    identifier = revise(root, change)
    data = report(root, identifier, aggregate(root, identifier, settings), settings)
    assert data["classification"]["unassigned_subject_reasons"] == {"outside_target": 1}
    assert data["overall"]["confirmed_subjects_after"] == 0
    assert data["overall"]["subject_mass"] == 0
    assert all(row["effective_sample_size"] == 0 for row in data["support"])
    assert not data["usefulness_gates"][DOMAIN]["passed"]


@pytest.mark.parametrize(("known", "weak"), [(0, True), (9, True), (10, False), (11, False)])
def test_condition_four_weak_correction_is_advisory_and_requires_a_majority(
    tmp_path, settings, known, weak,
):
    root = tmp_path / "snapshot"
    snapshot(root, 20)

    def change(db, manifest):
        for index, (aid, raw) in enumerate(
            db.execute("SELECT id, data FROM assets ORDER BY id").fetchall()
        ):
            if index < known:
                continue
            data = json.loads(raw)
            data["scene_attributes"] = {}
            db.execute("UPDATE assets SET data=? WHERE id=?", [canonical(data), aid])

    identifier = revise(root, change)
    stats = aggregate(root, identifier, settings)
    data = report(root, identifier, stats, settings)
    gate = data["usefulness_gates"][DOMAIN]
    wall = next(r for r in gate["correction"] if r["target_parts"] == ["wall"])
    assert wall["no_information_rate"] == (20 - known) / 20
    assert wall["correction_rate"] == known / 20
    assert ("weak_correction" in wall["quality_flags"]) is weak
    assert gate["passed"] and wall["passed"]
    assert "weak_correction" not in cell(stats)["quality"]["flags"]
    assert data["support"][0]["quality"] == stats["rows"][0]["quality"]
    rendered = markdown(data).split("## 条件・役割別支持")[0]
    expected_flag = "weak_correction" if weak else "なし"
    assert (f"| real_building | wall | True | 20 | {wall['effective_sample_size']:.6g} | "
            f"{known / 20:.6g} | {(20 - known) / 20:.6g} | {expected_flag} |") in rendered
