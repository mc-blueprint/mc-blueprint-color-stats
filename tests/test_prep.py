from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw

from colorstats.analyze.prep import _inspect, _quality, prepare
from colorstats.queue.core import Claim


def _scene(path: Path, size=(640, 480)) -> None:
    image = Image.new("RGB", size, "#5b8c3a")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 100, 560, 400), fill="#8b6b45")
    draw.rectangle((180, 170, 460, 400), fill="#ad3434")
    draw.line((80, 100, 320, 10, 560, 100), fill="#dddddd", width=8)
    image.save(path)


def test_sha256_and_phash_detect_exact_and_near_duplicates(tmp_path):
    first = tmp_path / "first.png"
    exact = tmp_path / "exact.png"
    near = tmp_path / "near.png"
    _scene(first)
    _scene(exact)
    _scene(near)
    Image.open(near).resize((638, 480)).save(near)

    original = _inspect(first)
    identical = _inspect(exact)
    similar = _inspect(near)

    assert original["sha256"] == identical["sha256"]
    assert original["phash"] == identical["phash"]
    assert original["sha256"] != similar["sha256"]
    assert (int(original["phash"], 16) ^ int(similar["phash"], 16)).bit_count() <= 6


def test_low_resolution_and_blur_are_flagged(tmp_path):
    low = tmp_path / "low.png"
    _scene(low, (64, 48))
    result = _inspect(low)
    assert _quality(result)["resolution_ok"] is False

    blurred = tmp_path / "blurred.png"
    _scene(blurred, (640, 480))
    image = Image.open(blurred).resize((16, 12)).resize((640, 480))
    image.save(blurred)
    assert _quality(_inspect(blurred))["blur_suspected"] is True


def test_reprocessing_produces_stable_analysis(tmp_path):
    image = tmp_path / "scene.png"
    _scene(image)
    first = _inspect(image)
    second = _inspect(image)
    for key in ("sha256", "phash", "width", "height", "sharpness", "watermark_suspected"):
        assert first[key] == second[key]


def test_colorful_wide_image_is_not_misclassified_as_low_color(tmp_path):
    image = Image.new("RGB", (800, 400))
    image.putdata(
        [(x % 256, y % 256, x * y % 256) for y in range(400) for x in range(800)]
    )
    path = tmp_path / "wide.png"
    image.save(path)
    result = _inspect(path)
    assert result["colors"] == 257
    assert result["collage_suspected"] is True


def test_prepare_writes_deterministic_resized_file(tmp_path):
    source = tmp_path / "source.png"
    target = tmp_path / "derived" / "asset.jpg"
    _scene(source)
    token = uuid4()
    claim = Claim(
        id=uuid4(),
        token=token,
        stage="prep",
        asset_id=uuid4(),
        config_hash="0" * 64,
        payload={
            "input_path": str(source),
            "derived_path": str(target),
            "license_class": "open",
            "taxonomy_version": "v1",
        },
        attempt=1,
        started_at=datetime.now(UTC),
    )

    first = prepare(claim)
    first_bytes = first.files[0][0].read_bytes()
    second = prepare(claim)

    assert first.files[0][1] == target
    assert first_bytes == second.files[0][0].read_bytes()
    with Image.open(first.files[0][0]) as resized:
        assert resized.size == (512, 384)
