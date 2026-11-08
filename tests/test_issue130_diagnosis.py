import copy

import numpy as np
import pytest
from bench.issue130.diagnose import policy, role, stages, verify

from colorstats.analyze import region_policy
from colorstats.analyze.segment import _digest


def test_baseline_matches_production_union_conflict_and_missing():
    semantic = np.array([[0, 1, 8, 2, 12, 4, 21]], dtype=np.uint8)
    full = np.ones(semantic.shape, dtype=bool)
    labels = ["wall_main", "wall_secondary", "window_glass", "tree_trunk", "water", "door"]
    rows = [(label, full.copy(), 0.9) for label in labels[:-1]]
    before = copy.deepcopy(rows)
    result, removed, diagnostics = stages(semantic, rows, labels, "baseline")
    expected, _, metrics = region_policy.constrain(semantic, rows, labels)
    for label, mask in result["effective"]:
        np.testing.assert_array_equal(mask, expected[role(label)])
    assert diagnostics["conflict_pixels"] == metrics["excluded_pixels"]["conflict"]
    assert diagnostics["same_parent_duplicate_pixels"] > 0
    assert diagnostics["missing_roles"] > 0
    assert any(mask.any() for _, mask in removed["parent"])
    for original, current in zip(before, rows, strict=True):
        np.testing.assert_array_equal(original[1], current[1])


def test_specific_only_clips_candidates_never_promotes_whole_building():
    semantic = np.array([[1, 8, 8, 2, 12]], dtype=np.uint8)
    wall = np.array([[True, False, False, True, True]])
    window = np.array([[True, True, False, True, True]])
    rows = [("wall_main", wall, 0.36), ("window_glass", window, 0.99)]
    result, _, _ = stages(semantic, rows, ["wall_main", "window_glass"], "specific")
    masks = dict(result["effective"])
    np.testing.assert_array_equal(masks["wall_main"], [[True, False, False, False, False]])
    np.testing.assert_array_equal(masks["window_glass"], [[False, True, False, False, False]])


def test_threshold_is_strict_and_preserves_terrain():
    semantic = np.array([[1, 4, 21]], dtype=np.uint8)
    full = np.ones(semantic.shape, dtype=bool)
    rows = [("wall_main", full, 0.45), ("tree_trunk", full, 0.36), ("water", full, 0.36)]
    result, _, _ = stages(semantic, rows, [r[0] for r in rows], "specific45")
    assert not dict(result["effective"])["wall_main"].any()
    assert dict(result["effective"])["tree_trunk"].sum() == 1
    assert dict(result["effective"])["water"].sum() == 1


def test_score_does_not_resolve_conflict():
    semantic = np.array([[1]], dtype=np.uint8)
    full = np.ones(semantic.shape, dtype=bool)
    rows = [("wall_main", full, 0.99), ("cornice", full, 0.56)]
    result, _, diagnostic = stages(semantic, rows, [r[0] for r in rows], "specific55")
    assert diagnostic["conflict_pixels"] == 1
    assert not any(mask.any() for _, mask in result["effective"])


def test_experimental_hash_is_separate_and_json_order_independent():
    value = policy()
    assert value["version"] != region_policy.VERSION
    assert _digest(value) == _digest(dict(reversed(list(value.items()))))
    assert _digest(value) != region_policy.policy_hash()
    with pytest.raises(ValueError, match="固定候補"):
        stages(np.zeros((1, 1), dtype=np.uint8), [], [], "other")


def test_class_info_json_hash_ignores_checkout_line_endings(tmp_path, monkeypatch):
    monkeypatch.setattr(region_policy, "__file__", str(tmp_path / "region_policy.py"))
    path = tmp_path / "oneformer-classes.json"
    path.write_bytes(b'{\n  "0": "wall",\n  "1": "building"\n}\n')
    lf_hash = _digest(policy())
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert _digest(policy()) == lf_hash


def test_fixed_code_and_policy_mismatch_stop_before_reference_import(tmp_path):
    with pytest.raises(ValueError, match="policy"):
        verify({"policy_hash": "different"})
    path = tmp_path / "code.py"
    path.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="コード"):
        verify({"policy_hash": _digest(policy()), "files": {str(path): "different"}})
