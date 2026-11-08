import copy
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from colorstats.analyze import region_policy, segment, segment_models, visible_wall
from tests.test_region_policy import make_claim
from tests.test_region_policy import regional_payload as regional_payload
from tests.test_segment import payload as payload


def test_raw_part_is_subtracted_even_when_semantic_parent_rejects_part():
    semantic = np.zeros((1, 5), dtype=np.uint8)
    wall = np.ones(semantic.shape, dtype=bool)
    window = np.array([[True, False, True, False, False]])
    rows = [("wall_main", wall, 0.9), ("wall_secondary", wall.copy(), 0.8),
            ("window_glass", window, 0.4)]
    masks, reasons, metrics = visible_wall.constrain(semantic, rows, [row[0] for row in rows])
    np.testing.assert_array_equal(masks[visible_wall.WALL], ~window)
    assert metrics["wall_before_subtraction_pixels"] == 5
    assert metrics["wall_subtracted_pixels"] == 2
    assert metrics["wall_remaining_candidate_pixels"] == 3
    assert reasons["wall_parts"].sum() == 2
    assert wall.all() and not masks["real_building/window_glass"].any()


def test_unresolved_part_conflict_stays_void_and_terrain_unchanged():
    semantic = np.array([[1, 1, 4, 21, 2, 12]], dtype=np.uint8)
    full = np.ones(semantic.shape, dtype=bool)
    rows = [(label, full.copy(), confidence) for label, confidence in (
        ("wall_main", 0.99), ("cornice", 0.8), ("band_course", 0.56),
        ("tree_trunk", 0.36), ("vegetation_tree_canopy", 0.4), ("water", 0.36))]
    labels = [row[0] for row in rows]
    original, _, _ = region_policy.constrain(semantic, rows, labels)
    masks, reasons, _ = visible_wall.constrain(semantic, rows, labels)
    assert not masks[visible_wall.WALL].any()
    assert reasons["conflict"].sum() == 2
    for role in ("real_terrain/tree", "real_terrain/water"):
        np.testing.assert_array_equal(masks[role], original[role])


def test_missing_parts_do_not_create_masks_and_auxiliary_threshold_is_strict():
    semantic = np.ones((1, 4), dtype=np.uint8)
    full = np.ones(semantic.shape, dtype=bool)
    rows = [("wall_main", full, 0.56)]
    before, _, _ = visible_wall.constrain(semantic, rows, ["wall_main"])
    masks, _, _ = visible_wall.constrain(semantic, rows, ["wall_main"], [
        ("exclude/shop", full, 0.35)])
    np.testing.assert_array_equal(masks[visible_wall.WALL], before[visible_wall.WALL])
    masks, _, metrics = visible_wall.constrain(semantic, rows, ["wall_main"], [
        ("exclude/balcony", full, 0.36)])
    assert not masks[visible_wall.WALL].any()
    assert visible_wall.WALL in metrics["missing_roles"]
    with pytest.raises(ValueError, match="補助"):
        visible_wall.constrain(semantic, rows, ["wall_main"], [("other", full, 0.9)])


def visible_prediction(image, payload, parameters):
    semantic = np.ones((image.height, image.width), dtype=np.uint8)
    full = np.ones(semantic.shape, dtype=bool)
    window = np.zeros_like(full)
    balcony = window.copy()
    window[0, :4] = True
    balcony[1, :2] = True
    return semantic, [("wall_main", full, 0.9), ("wall_secondary", full.copy(), 0.8),
                      ("window_glass", window, 0.4), ("exclude/balcony", balcony, 0.4)], {}


def test_new_method_artifact_roundtrip_and_old_method_is_unchanged(regional_payload, monkeypatch):
    previous = segment.config_hash(regional_payload)
    regional_payload["method"] = visible_wall.METHOD
    monkeypatch.setattr(segment_models, "predict_regions", visible_prediction)
    assert segment.config_hash(regional_payload) != previous
    prepared = segment.prepare(make_claim(regional_payload, segment, "segment"))
    for temporary, target in prepared.files:
        temporary.replace(target)
    policy = prepared.data["region_policy"]
    assert policy["version"] == visible_wall.VERSION
    assert len(policy["wall_candidates"]) == 1
    assert all(not row["label"].startswith("exclude/") for row in prepared.data["regions"])
    assert policy["policy_hash"] == visible_wall.policy_hash()
    contract = {**policy, "run_id": "fixed"}
    value = {**regional_payload, "region_run_id": "fixed", "region_policy": contract}
    masks = region_policy.load_masks(value)
    assert masks[visible_wall.WALL].sum() == 42
    changed = copy.deepcopy(value)
    changed["region_policy"]["version"] = region_policy.VERSION
    with pytest.raises(ValueError, match="hash"):
        region_policy.load_masks(changed)
    changed = copy.deepcopy(value)
    changed["region_policy"]["wall_candidates"][0]["mask"]["sha256"] = "changed"
    with pytest.raises(ValueError, match="SHA"):
        region_policy.load_masks(changed)
    with Image.open(prepared.data["regions"][0]["mask_path"]) as image:
        assert (np.asarray(image) != 0).sum() == 48


def test_visible_hash_ignores_crlf_and_runner_refuses_legacy(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from ops.deploy.m3_analysis import _check_policy_reuse

    monkeypatch.setattr(region_policy, "__file__", str(tmp_path / "region_policy.py"))
    path = Path(region_policy.__file__).with_name("oneformer-classes.json")
    path.write_text(json.dumps({"0": "wall", "1": "building"}, indent=2), encoding="utf-8")
    expected = visible_wall.policy_hash()
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert visible_wall.policy_hash() == expected
    source = SimpleNamespace(parameters={"payload": {"method": region_policy.METHOD}})
    with pytest.raises(ValueError, match="旧segment"):
        _check_policy_reuse(source, {"segment": {"method": visible_wall.METHOD}})
