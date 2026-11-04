import json
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import numpy as np
import pytest
from PIL import Image

from colorstats.analyze import segment
from colorstats.queue.core import Claim


@pytest.fixture
def payload(tmp_path):
    image = tmp_path / "scene.png"
    Image.new("RGB", (8, 6), "orange").save(image)
    paths = {}
    for name in ("sam2", "dino"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "model.safetensors").write_bytes(name.encode())
        (directory / "config.json").write_text("{}")
        paths[name] = str(directory)
    return {
        "method": "sam2-dino", "model_paths": paths, "input_path": str(image),
        "output_path": str(tmp_path / "segments.json"), "license_class": "open",
        "taxonomy_version": "0.1.0", "prompts": {"wall_main": "building wall"},
    }


def claim(payload):
    return Claim(uuid.uuid4(), uuid.uuid4(), "segment", uuid.uuid4(),
                 segment.config_hash(payload), payload, 1, datetime.now(UTC))


def prediction(image, method, paths, model_hashes, prompts, threshold, text_threshold):
    mask = np.zeros((image.height, image.width), dtype=np.bool_)
    mask[1:5, 2:7] = True
    mask[2, 3] = False
    return [("wall_main", mask, 0.8)], {"inference_seconds": 0.01, "batch_size": 1}


def test_masks_cvat_and_metadata(payload, monkeypatch):
    monkeypatch.setattr(segment, "predict", prediction)
    job = claim(payload)
    result = segment.prepare(job)
    assert result.info.model_name == "sam2-dino"
    assert result.info.license_class == "open"
    assert len(result.info.weights_hash) == 64
    assert result.info.parameters["metrics"]["mask_bytes"] > 0
    assert result.data["regions"][0]["bbox"] == [2, 1, 7, 5]
    assert result.data["regions"][0]["area_ratio"] == pytest.approx(19 / 48)
    assert len(result.files) == 3
    assert all(temporary.parent == target.parent and not target.exists()
               for temporary, target in result.files)
    mask_path, _ = result.files[0]
    mask = np.asarray(Image.open(mask_path)) != 0
    assert not mask[2, 3] and mask.sum() == 19
    xml_path, _ = result.files[1]
    node = ET.parse(xml_path).find("image/mask")
    lengths = list(map(int, node.attrib["rle"].split(",")))
    pixels = np.concatenate([np.full(length, i % 2, dtype=np.bool_)
                             for i, length in enumerate(lengths)])
    np.testing.assert_array_equal(pixels.reshape(4, 5), mask[1:5, 2:7])
    assert node.attrib["label"] == "wall_main"
    assert json.loads(result.files[-1][0].read_text())["metrics"]["regions"] == 1


def test_config_tracks_real_files_and_prompts(payload):
    original = segment.config_hash(payload)
    path = payload["model_paths"]["dino"]
    from pathlib import Path

    (Path(path) / "model.safetensors").write_bytes(b"changed")
    assert segment.config_hash(payload) != original
    original = segment.config_hash(payload)
    payload["prompts"]["wall_main"] = "stone wall"
    assert segment.config_hash(payload) != original
    original = segment.config_hash(payload)
    Image.new("RGB", (8, 6), "blue").save(payload["input_path"])
    assert segment.config_hash(payload) != original


def test_changed_configuration_fails_before_inference(payload, monkeypatch):
    job = claim(payload)
    payload["threshold"] = 0.8
    monkeypatch.setattr(segment, "predict", lambda *args: pytest.fail("推論してはいけない"))
    with pytest.raises(ValueError, match="設定ハッシュ"):
        segment.prepare(job)


@pytest.mark.parametrize("patch", [
    {"method": "unknown"}, {"method": "sam3.1"}, {"prompts": {"unknown": "wall"}},
    {"prompts": {"wall_main": ""}}, {"taxonomy_version": "9.0.0"},
    {"threshold": 0}, {"license_class": "unknown"},
])
def test_invalid_contract(payload, patch):
    payload.update(patch)
    with pytest.raises(ValueError):
        segment.config_hash(payload)


def test_empty_detection_is_valid(payload, monkeypatch):
    monkeypatch.setattr(segment, "predict", lambda *args: ([], {}))
    result = segment.prepare(claim(payload))
    assert result.data["regions"] == []
    assert result.info.parameters["metrics"]["mask_bytes"] == 0
    assert len(result.files) == 2


def test_bad_mask_does_not_produce_success(payload, monkeypatch):
    monkeypatch.setattr(segment, "predict", lambda *args: (
        [("wall_main", np.ones((3, 3), dtype=np.bool_), 0.9)], {}
    ))
    with pytest.raises(ValueError, match="推論結果"):
        segment.prepare(claim(payload))


@pytest.mark.parametrize("values,expected", [
    (("open", "noncommercial"), "noncommercial"),
    (("academic_only", "noncommercial"), "restricted"),
    (("open", "restricted"), "restricted"),
])
def test_license_does_not_relax(values, expected):
    assert segment._license(*values) == expected
