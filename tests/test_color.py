import json
import subprocess
import sys
from datetime import UTC, datetime
from uuid import uuid4

import numpy as np
import pytest
from PIL import Image

from colorstats.analyze.color import extract_colors, prepare
from colorstats.colors import rgb_to_oklab
from colorstats.queue.core import Claim


def test_optional_colour_plotting_stub_does_not_break_later_imports():
    subprocess.run(
        [sys.executable, "-c", (
            "import importlib.util,sys; "
            "from colorstats.colors import rgb_to_oklab; "
            "module=sys.modules.get('matplotlib'); "
            "assert module is None or module.__spec__ is not None; "
            "spec=importlib.util.find_spec('matplotlib'); "
            "assert spec is None or spec.name == 'matplotlib'; "
            "assert rgb_to_oklab(__import__('numpy').array([[1.0,0.0,0.0]])).shape == (1,3)"
        )],
        capture_output=True, text=True, check=True,
    )


def scene():
    rgb = np.full((20, 20, 3), (255, 0, 0), dtype=np.uint8)
    rgb[:, 15:] = (0, 0, 255)
    return Image.fromarray(rgb)


def test_known_colors_and_areas():
    rows = extract_colors(scene())
    assert [row["area_ratio"] for row in rows] == [0.75, 0.25]
    for row, rgb in zip(rows, ((1, 0, 0), (0, 0, 1)), strict=True):
        expected = rgb_to_oklab(np.array([rgb]))[0]
        np.testing.assert_allclose(row["observed_oklab"]["dominant"], expected, atol=1e-12)
        for quantile in row["observed_oklab"]["quantiles"]:
            np.testing.assert_allclose(quantile["value"], expected, atol=1e-12)


def test_alpha_clipping_and_mask_define_valid_area():
    image = Image.new("RGBA", (8, 1))
    image.putdata([
        (255, 0, 0, 255), (0, 0, 255, 255), (0, 255, 0, 255),
        (255, 0, 0, 0), (255, 0, 0, 254), (5, 5, 5, 255),
        (250, 250, 250, 255), (0, 0, 0, 255),
    ])
    mask = np.ones((1, 8), dtype=bool)
    mask[0, 2] = False
    rows = extract_colors(image, mask)
    assert len(rows) == 2
    assert [row["area_ratio"] for row in rows] == [0.5, 0.5]


@pytest.mark.parametrize("rgb", [(0, 0, 0), (255, 255, 255), (5, 5, 5), (250, 250, 250)])
def test_no_valid_pixels_fail(rgb):
    with pytest.raises(ValueError, match="有効画素"):
        extract_colors(Image.new("RGB", (2, 2), rgb))


def test_mask_size_and_empty_mask():
    with pytest.raises(ValueError, match="mask"):
        extract_colors(scene(), np.ones((2, 2), dtype=bool))
    with pytest.raises(ValueError, match="mask"):
        extract_colors(scene(), np.ones((20, 20), dtype=np.uint8))
    with pytest.raises(ValueError, match="有効画素"):
        extract_colors(scene(), np.zeros((20, 20), dtype=bool))


@pytest.mark.parametrize("clusters", [0, -1, 1.5, True])
def test_invalid_clusters(clusters):
    with pytest.raises(ValueError, match="clusters"):
        extract_colors(scene(), clusters=clusters)


def test_single_pixel_and_nonclipped_boundary():
    for rgb in ((6, 6, 6), (249, 249, 249), (255, 0, 0)):
        rows = extract_colors(Image.new("RGB", (1, 1), rgb))
        assert len(rows) == 1
        assert rows[0]["area_ratio"] == 1


def test_fixed_seed_on_many_colors():
    rng = np.random.default_rng(123)
    image = Image.fromarray(rng.integers(10, 240, (40, 40, 3), dtype=np.uint8))
    first = extract_colors(image)
    extract_colors(scene())
    assert first == extract_colors(image)
    assert len(first) == 5
    assert sum(row["area_ratio"] for row in first) == pytest.approx(1)


def claim_for(source, target, **payload):
    return Claim(
        id=uuid4(), token=uuid4(), stage="color", asset_id=uuid4(), config_hash="c" * 64,
        payload={
            "input_path": str(source), "output_path": str(target),
            "license_class": "open", "taxonomy_version": "0.1.0", **payload,
        },
        attempt=1, started_at=datetime.now(UTC),
    )


def test_prepare_is_stable_and_keeps_output_unpublished(tmp_path):
    source = tmp_path / "scene.png"
    target = tmp_path / "derived" / "colors.json"
    mask_path = tmp_path / "mask.png"
    scene().save(source)
    Image.new("L", (20, 20), 255).save(mask_path)
    claim = claim_for(source, target, mask_path=str(mask_path))
    first = prepare(claim)
    content = first.files[0][0].read_bytes()
    assert content == prepare(claim).files[0][0].read_bytes()
    assert json.loads(content) == first.data
    assert not target.exists()
    assert first.info.parameters["seed"] == 0
    assert first.data["asset_id"] == str(claim.asset_id)
