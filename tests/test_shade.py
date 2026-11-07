import sys
from contextlib import nullcontext
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import colour
import numpy as np
import pytest
from PIL import Image

from colorstats.analyze.shade import config_hash, correct, observations
from colorstats.analyze.shade_evaluation import compare


def test_gray_world_uses_linear_rgb_and_keeps_input():
    pixels = np.array([[[80, 120, 160], [120, 160, 200]]], dtype=np.uint8)
    image = Image.fromarray(pixels)
    result = correct(image, "gray-world")
    linear = colour.cctf_decoding(result, function="sRGB")
    np.testing.assert_allclose(linear.mean(axis=(0, 1)), linear.mean(), atol=1e-10)
    np.testing.assert_array_equal(np.asarray(image), pixels)
    np.testing.assert_allclose(correct(image, "none"), pixels / 255)
    with pytest.raises(ValueError, match="平均が0"):
        correct(Image.new("RGB", (2, 2), "red"), "gray-world")


def test_observations_use_same_valid_pixels_and_report_missing(tmp_path):
    image = Image.fromarray(np.array([[[0, 0, 0], [100, 140, 180], [255, 255, 255]]],
                                    dtype=np.uint8))
    mask = tmp_path / "mask.png"
    Image.new("L", image.size, 255).save(mask)
    rows = [{"region_id": "1", "label_source": "model", "mask_path": str(mask), "size": [3, 1]}]
    records = observations(image, correct(image, "none"), rows)
    row = records[0]["observations"][0]
    assert row["material_confidence"] == pytest.approx(1 / 3)
    assert row["observed_oklab"] == row["material_oklab"]
    Image.new("L", image.size, 0).save(mask)
    assert observations(image, correct(image, "none"), rows) == []


def test_hash_checks_mask_image_method_and_weights(tmp_path, monkeypatch):
    monkeypatch.setattr("colorstats.analyze.shade._implementation", lambda: {"test": "fixed"})
    path = tmp_path / "image.png"
    Image.new("RGB", (2, 2), "tan").save(path)
    payload = {"method": "none", "input_path": str(path), "output_path": "shade.json",
               "region_run_id": str(uuid4()), "regions": [], "license_class": "open"}
    baseline = config_hash(payload)
    assert config_hash({**payload, "method": "gray-world"}) != baseline
    Image.new("RGB", (2, 2), "red").save(path)
    assert config_hash(payload) != baseline
    with pytest.raises(ValueError, match="評価専用"):
        config_hash({**payload, "method": "intrinsic"})
    payload.update(method="intrinsic", evaluation_only=True, model_path=str(tmp_path))
    for i in range(4):
        (tmp_path / f"stage_{i}.pt").write_bytes(bytes([i]))
    baseline = config_hash(payload)
    (tmp_path / "stage_1.pt").write_bytes(b"changed")
    assert config_hash(payload) != baseline


def sample(asset, method, value, *, subject="church", source="model"):
    return {"subject_id": subject, "asset_id": asset, "sha256": asset,
            "label_source": source, "label": "wall_main", "method": method,
            "material_oklab": [value, 0, 0]}


def test_comparison_matches_pairs_and_macro_averages_subjects():
    rows = [sample(asset, method, value)
            for method in ("none", "gray-world", "intrinsic")
            for asset, value in (("a", 0.2), ("b", 0.4), ("c", 0.6))]
    rows.remove(sample("c", "intrinsic", 0.6))
    rows += [sample(asset, method, value, subject="castle")
             for method in ("none", "gray-world", "intrinsic")
             for asset, value in (("d", 0.2), ("e", 0.8))]
    result = compare(rows)
    assert result["model"]["pairs"] == 2
    assert result["model"]["subjects"] == 2
    assert result["model"]["methods"]["none"]["mean_delta_e_ok"] == pytest.approx(0.4)
    assert result["human"]["methods"]["none"]["mean_delta_e_ok"] is None
    assert compare(list(reversed(rows))) == result
    with pytest.raises(ValueError, match="重複"):
        compare(rows + [rows[0]])
    with pytest.raises(ValueError, match="重複asset"):
        compare(rows + [{**rows[0], "asset_id": "duplicate"}])


def test_human_and_model_are_not_mixed():
    rows = [sample("a", method, 0.2, source="human")
            for method in ("none", "gray-world", "intrinsic")]
    rows += [sample("b", method, 0.4) for method in ("none", "gray-world", "intrinsic")]
    assert compare(rows)["model"]["pairs"] == 0
    assert compare(rows)["human"]["pairs"] == 0


def test_intrinsic_seeds_numpy_and_restores_state_on_success_and_failure(monkeypatch):
    torch = SimpleNamespace(
        manual_seed=Mock(), are_deterministic_algorithms_enabled=lambda: False,
        is_deterministic_algorithms_warn_only_enabled=lambda: False,
        use_deterministic_algorithms=Mock(), inference_mode=nullcontext,
        backends=SimpleNamespace(cudnn=SimpleNamespace(flags=lambda **kwargs: nullcontext())),
    )
    pipeline = ModuleType("intrinsic.pipeline")
    pipeline.run_pipeline = lambda *args, **kwargs: {
        "hr_alb": np.random.random((2, 2, 3)).astype(np.float32),
    }
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "intrinsic", ModuleType("intrinsic"))
    monkeypatch.setitem(sys.modules, "intrinsic.pipeline", pipeline)
    monkeypatch.setattr("colorstats.analyze.shade._models", lambda *args: {})
    image = Image.new("RGB", (2, 2), "tan")
    state = np.random.get_state()
    first = correct(image, "intrinsic")
    second = correct(image, "intrinsic")
    np.testing.assert_array_equal(first, second)
    np.testing.assert_array_equal(np.random.get_state()[1], state[1])
    pipeline.run_pipeline = Mock(side_effect=RuntimeError("推論失敗"))
    with pytest.raises(RuntimeError, match="推論失敗"):
        correct(image, "intrinsic")
    np.testing.assert_array_equal(np.random.get_state()[1], state[1])
    torch.use_deterministic_algorithms.assert_called_with(False, warn_only=False)


def test_intrinsic_excludes_transparent_rgb_from_estimation(monkeypatch):
    torch = SimpleNamespace(
        manual_seed=Mock(), are_deterministic_algorithms_enabled=lambda: False,
        is_deterministic_algorithms_warn_only_enabled=lambda: False,
        use_deterministic_algorithms=Mock(), inference_mode=nullcontext,
        backends=SimpleNamespace(cudnn=SimpleNamespace(flags=lambda **kwargs: nullcontext())),
    )
    pipeline = ModuleType("intrinsic.pipeline")
    pipeline.run_pipeline = Mock(side_effect=lambda models, rgb, **kwargs: {"hr_alb": rgb})
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "intrinsic", ModuleType("intrinsic"))
    monkeypatch.setitem(sys.modules, "intrinsic.pipeline", pipeline)
    monkeypatch.setattr("colorstats.analyze.shade._models", lambda *args: {})
    pixels = np.array([[[80, 120, 160, 255], [200, 160, 120, 255], [0, 0, 255, 0]]],
                      dtype=np.uint8)
    original = pixels.copy()
    first = correct(Image.fromarray(pixels), "intrinsic")
    first_input = pipeline.run_pipeline.call_args.args[1].copy()
    np.testing.assert_allclose(first_input[0, 2], [140 / 255] * 3)
    np.testing.assert_array_equal(pixels, original)
    pixels[0, 2, :3] = [255, 0, 0]
    second = correct(Image.fromarray(pixels), "intrinsic")
    np.testing.assert_array_equal(first_input, pipeline.run_pipeline.call_args.args[1])
    np.testing.assert_array_equal(first, second)
    pipeline.run_pipeline.reset_mock()
    pixels[:, :, 3] = 0
    correct(Image.fromarray(pixels), "intrinsic")
    pipeline.run_pipeline.assert_not_called()
