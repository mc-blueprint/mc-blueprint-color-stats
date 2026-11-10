import hashlib
import uuid
from types import SimpleNamespace

import pytest
from PIL import Image

from colorstats.analyze import prep
from colorstats.privacy_review import _check_prep_origin, decision, is_new


@pytest.mark.parametrize("change", [None, "raw", "output", "profile", "recorded_sha"])
@pytest.mark.parametrize("with_rendition", [False, True])
def test_取得画像SHAのない旧prepは再生成して固定出力を照合する(tmp_path, change, with_rendition):
    raw = tmp_path / "raw.png"
    Image.new("RGB", (80, 60), "orange").save(raw)
    claim = SimpleNamespace(asset_id=uuid.uuid4(), token=uuid.uuid4(), payload={
        "input_path": str(raw), "derived_path": str(tmp_path / "prep.jpg"),
        "license_class": "open", "taxonomy_version": "0.1.0"})
    prepared = prep.prepare(claim)
    output_sha = hashlib.sha256(prepared.files[0][0].read_bytes()).hexdigest()
    source = raw.read_bytes()
    source_sha = hashlib.sha256(source).hexdigest()
    parameters = {"max_size": [512, 512], "phash_distance": 6}
    if with_rendition:
        parameters.update(rendition={"requested_width": 1024},
                          transform={"mode": "RGB", "resample": "LANCZOS", "format": "JPEG",
                                     "quality": 90, "optimize": True})
    if change == "raw":
        Image.new("RGB", (80, 60), "blue").save(raw)
        source = raw.read_bytes()
    elif change == "output":
        output_sha = "0" * 64
    elif change == "profile":
        parameters["max_size"] = [256, 256]
    elif change == "recorded_sha":
        parameters["input_sha256"] = "0" * 64
    if change is None:
        _check_prep_origin(parameters, source, source_sha, output_sha)
    else:
        with pytest.raises(PermissionError):
            _check_prep_origin(parameters, source, source_sha, output_sha)


@pytest.mark.parametrize("change", ["unknown_key", "transform", "rendition"])
def test_旧rendition形式でも未知の処理条件は拒否する(change):
    parameters = {"max_size": [512, 512], "phash_distance": 6, "rendition": {},
                  "transform": {"mode": "RGB", "resample": "LANCZOS", "format": "JPEG",
                                "quality": 90, "optimize": True}}
    if change == "unknown_key":
        parameters["unknown"] = True
    elif change == "transform":
        parameters["transform"]["quality"] = 80
    else:
        parameters["rendition"] = None
    with pytest.raises(PermissionError, match="前処理版"):
        _check_prep_origin(parameters, b"", "unused", "unused")


@pytest.mark.parametrize("people,pixels,accepted", [
    ("absent", 0, True),  # 像・絵も両方の根拠が陰性であることを必要とする。
    ("present", 0, False), ("present", 1, False), ("present", 500, False),
    ("absent", 1, False), ("uncertain", 0, False), (None, 0, False),
    ("absent", None, False),
])
def test_二つの陰性根拠以外は採用しない(people, pixels, accepted):
    assert (decision(people, pixels)["decision"] == "accepted") is accepted


def test_新版の欠損参照を旧契約として扱わない():
    assert is_new({"contract": "image-review-v1"})
    assert is_new({"privacy_review_run_id": "missing"})
    assert not is_new({"person_mask": None})


@pytest.mark.parametrize("key", ["contract", "image_gate_hash", "privacy_review_hash",
                                 "region_policy_hash", "image_gate_input_sha256",
                                 "person_mask_sha256", "analysis_domain"])
def test_新版の項目はnullだけでも旧契約にならない(key):
    assert is_new({key: None})
