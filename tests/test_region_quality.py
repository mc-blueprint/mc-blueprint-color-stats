"""固定地形品質の範囲拡張と、異なるモデル・promptの採用を拒否する。"""

import copy
from pathlib import Path

import pytest

from colorstats.stats import region_quality


def parameters(quality):
    frozen = quality["region_validation"]["freeze"]
    return {"payload": copy.deepcopy(quality["segment"]),
            "region_policy_hash": frozen["policy_hash"],
            "parent_table": frozen["parent_table"], "transform": frozen["transform"],
            "models": {"oneformer": frozen["oneformer"], **{
                name: {"files": {key: value for key, value in files.items()
                                 if Path(key).suffix in {
                                     ".json", ".txt", ".safetensors", ".model"}}}
                for name, files in frozen["models"].items()}}}


def test_fixed_terrain_roles_and_default_diagnostics():
    quality = region_quality.load(Path(__file__).resolve().parents[1])
    assert region_quality.approved_roles(quality, parameters(quality)) == {
        "real_terrain/water", "real_terrain/tree"}
    assert region_quality.approved_roles({}, {}) == set()
    assert not quality["quality"]["quality_eligible_all_parts"]


@pytest.mark.parametrize("change", ["building", "child", "threshold", "prompt", "model", "policy"])
def test_other_scope_or_execution_identity_is_rejected(change):
    quality = region_quality.load(Path(__file__).resolve().parents[1])
    current = copy.deepcopy(parameters(quality))
    if change == "building":
        quality["group_members"]["real_building/wall"] = ["wall_main"]
    elif change == "child":
        quality["supported_by_domain"]["real_terrain"] = ["tree_trunk"]
    elif change == "threshold":
        current["payload"]["threshold"] = quality["segment"]["threshold"] = 0.5
    elif change == "prompt":
        current["payload"]["prompts"]["water"] = "lake"
    elif change == "model":
        current["models"]["dino"]["files"]["model.safetensors"] = "changed"
    else:
        current["region_policy_hash"] = "changed"
    with pytest.raises(ValueError):
        region_quality.approved_roles(quality, current)
    assert "real_building/wall" not in region_quality.GROUPS
