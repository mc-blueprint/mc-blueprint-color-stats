"""モデル判定を使う評価で群・領域・由来を混同しないことを検証する。"""

import copy
import runpy
from pathlib import Path

import pytest

from colorstats.analyze.shade import METHODS
from colorstats.analyze.shade_evaluation import compare

evaluation = runpy.run_path(Path(__file__).resolve().parents[1] / "bench/issue46/run_sol.py")


def test_correct_filter_precedes_weighted_mean_and_pair_selection():
    records = []
    for method in METHODS:
        for asset, verdict, value, weight in (
            ("a", "correct", 0.2, 3), ("a", "spill", 0.9, 30),
            ("a", "correct", 0.6, 1), ("b", "correct", 0.5, 1),
            ("c", "wrong_label", 0.1, 1),
        ):
            records.append({"subject_id": "church", "asset_id": asset, "sha256": asset,
                            "label": "wall_main", "method": method, "verdict": verdict,
                            "valid_pixels": weight, "material_oklab": [value, 0, 0]})
    samples = evaluation["aggregate"](records)
    selected = [r for r in samples if r["label_source"] == "sol-correct"]
    assert {r["asset_id"] for r in selected} == {"a", "b"}
    assert selected[0]["material_oklab"][0] == pytest.approx(0.3)
    result = compare(samples)
    assert result["model"]["pairs"] == 3
    assert result["sol-correct"]["pairs"] == 1
    assert result["sol-correct"]["methods"]["none"]["mean_delta_e_ok"] == pytest.approx(0.2)
    assert result["human"]["subjects"] == 0
    assert evaluation["aggregate"](list(reversed(records))) == samples


def test_identity_requires_same_name_and_existing_membership():
    manifest = {"assets": [{"asset_id": aid, "building_id": "church"} for aid in ("a", "b")]}
    identity = {"assets": {aid: {"building_name": "教会", "building_id": "church",
                                "comparison": "match", "judged_group": ["a", "b"],
                                "candidate_group": ["a", "b"]} for aid in ("a", "b")}}
    assert evaluation["select_groups"](manifest, identity) == [
        {"subject_id": "church", "building_name": "教会", "asset_ids": ["a", "b"]}]
    for key, value in (("building_name", "別の教会"), ("comparison", "mismatch"),
                       ("judged_group", ["a"]), ("building_id", "other")):
        changed = copy.deepcopy(identity)
        changed["assets"]["b"][key] = value
        if key == "building_name":
            assert evaluation["select_groups"](manifest, changed) == []
        else:
            with pytest.raises(ValueError):
                evaluation["select_groups"](manifest, changed)
