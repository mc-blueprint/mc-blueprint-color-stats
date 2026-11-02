import json
from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

from colorstats.analyze.color import config_hash, extract_colors, extract_relations, prepare
from tests.test_color import claim_for, scene


def test_model_and_original_polygon_use_color_coordinates(tmp_path):
    source = tmp_path / "scene.png"
    scene().save(source)
    model = tmp_path / "model.png"
    mask = np.zeros((10, 10), dtype=np.uint8)
    mask[:, :5] = 255
    Image.fromarray(mask).save(model)
    human = tmp_path / "human.json"
    human.write_text(json.dumps({
        "format": "polygon-pixels-v1",
        "points": [[60, 0], [80, 0], [80, 80], [60, 80]],
    }))
    claim = claim_for(source, tmp_path / "colors.json", region_run_id="source", regions=[
        {"region_id": "a", "label_source": "model", "mask_path": str(model), "size": [10, 10]},
        {"region_id": "b", "label_source": "human", "mask_path": str(human), "size": [80, 80]},
    ])
    claim = replace(claim, config_hash=config_hash(claim.payload))
    result = prepare(claim)
    assert result.data["observations"][0]["area_ratio"] == 0.75
    assert [row["area"] for row in result.data["regions"]] == [200, 100]
    assert all(len(row["observations"]) == 1 for row in result.data["regions"])
    relation = result.data["relations"][0]
    assert relation["area_ratio"] == 0.5
    assert relation["delta_e_ok"] > 0
    assert not (tmp_path / "colors.json").exists()
    model.write_bytes(b"changed")
    with pytest.raises(ValueError, match="ハッシュ"):
        prepare(claim)


def test_relation_direction_hue_wrap_and_achromatic():
    def part(key, lightness, chroma, hue, area):
        radians = np.radians(hue)
        return {"region_id": key, "area": area, "observations": [{"observed_oklab": {
            "dominant": [lightness, chroma * np.cos(radians), chroma * np.sin(radians)],
        }}]}

    a, b = part("a", 0.3, 0.1, 170, 10), part("b", 0.5, 0.2, -170, 30)
    row = extract_relations([a, b])[0]
    assert row["delta_l"] == pytest.approx(0.2)
    assert row["delta_c"] == pytest.approx(0.1)
    assert row["delta_h"] == pytest.approx(20)
    assert row["area_ratio"] == 3
    reverse = extract_relations([b, a])[0]
    assert reverse["delta_h"] == pytest.approx(-20)
    assert reverse["delta_e_ok"] == pytest.approx(row["delta_e_ok"])
    assert extract_relations([a, part("c", 0.4, 0, 0, 20)])[0]["delta_h"] is None
    assert extract_relations([a]) == []


def test_empty_region_run_preserves_baseline(tmp_path):
    source = tmp_path / "scene.png"
    scene().save(source)
    claim = claim_for(source, tmp_path / "out.json", region_run_id="source", regions=[])
    result = prepare(replace(claim, config_hash=config_hash(claim.payload)))
    assert len(result.data["observations"]) == 2
    assert result.data["relations"] == result.data["regions"] == []


@pytest.mark.parametrize("value", [6, 128, 249])
def test_rgb_gray_has_undefined_hue(value):
    parts = [{"region_id": key, "area": 1, "observations": extract_colors(
        Image.new("RGB", (1, 1), rgb),
    )} for key, rgb in (("a", (255, 0, 0)), ("b", (value, value, value)))]
    assert extract_relations(parts)[0]["delta_h"] is None


def test_region_without_valid_pixels_fails(tmp_path):
    source = tmp_path / "scene.png"
    scene().save(source)
    mask = tmp_path / "empty.png"
    Image.new("L", (20, 20)).save(mask)
    claim = claim_for(source, tmp_path / "out.json", region_run_id="source", regions=[{
        "region_id": "a", "label_source": "model", "mask_path": str(mask), "size": [20, 20],
    }])
    with pytest.raises(ValueError, match="有効画素"):
        prepare(replace(claim, config_hash=config_hash(claim.payload)))
