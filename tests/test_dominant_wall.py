import numpy as np
import pytest
from bench.issue130.dominant_eval import choose, summarize
from PIL import Image

from colorstats.analyze.color import extract_colors
from colorstats.analyze.dominant_wall import estimate
from colorstats.colors import rgb_to_oklab


def test_largest_cluster_includes_white_wall_and_respects_front():
    rgb = np.full((4, 8, 3), 255, dtype=np.uint8)
    rgb[:, :2] = [0, 0, 0]
    rgb[:, 6:] = [255, 0, 0]
    front = np.ones((4, 8), dtype=bool)
    front[:, 6:] = False
    before = rgb.copy()
    result = estimate(Image.fromarray(rgb), front, clusters=3)
    np.testing.assert_allclose(result["color"], rgb_to_oklab(np.ones((1, 3)))[0])
    assert result["dominant_area_ratio"] == 2 / 3
    np.testing.assert_array_equal(rgb, before)
    # 既存stageの黒白除外は既定値のまま維持する。
    rows = extract_colors(Image.fromarray(rgb))
    assert len(rows) == 1


def test_equal_area_is_missing_and_single_color_is_valid():
    rgb = np.zeros((2, 4, 3), dtype=np.uint8)
    rgb[:, :2] = 255
    front = np.ones((2, 4), dtype=bool)
    assert estimate(Image.fromarray(rgb), front, clusters=2)["missing_reason"] == "dominant_tie"
    result = estimate(Image.new("RGB", (4, 2), "black"), front, clusters=5)
    assert result["missing_reason"] is None
    assert result["cluster_count"] == 1
    np.testing.assert_allclose(result["color"], [0, 0, 0], atol=1e-12)


def test_missing_front_and_transparent_are_explicit():
    front = np.zeros((2, 2), dtype=bool)
    image = Image.new("RGBA", (2, 2))
    assert estimate(image, front, clusters=2)["missing_reason"] == "front_not_found"
    front[:] = True
    assert estimate(image, front, clusters=2)["missing_reason"] == "no_opaque_pixels"
    with pytest.raises(ValueError, match="front"):
        estimate(image, front.astype(np.uint8), clusters=2)
    with pytest.raises(ValueError, match="clusters"):
        estimate(image, front, clusters=0)


def test_selection_does_not_hide_missing_images_for_smaller_error():
    reports = [
        {"valid": 2, "missing_rate": 0.5, "median": 0.0, "p90": 0.0},
        {"valid": 8, "missing_rate": 0.2, "median": 0.03, "p90": 0.05},
    ]
    assert choose(reports) == (1, True)
    reports[1]["missing_rate"] = 0.6
    assert choose(reports) == (0, False)
    values = summarize([{"delta_ok": value, "missing_reason": None if value is not None
                         else "front_not_found"} for value in (0.01, 0.03, None, None)])
    assert values["images"] == 4 and values["missing_rate"] == 0.5
    assert values["median"] == 0.02
    assert values["p90"] == pytest.approx(0.028)
