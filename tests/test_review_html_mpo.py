"""合成MPOの先頭フレームと原画像byteを、入力側と提示側で照合する。"""

import base64
import hashlib
import io

import pytest
from bench.issue114 import mobile
from PIL import Image, ImageDraw

from colorstats import image_gate, privacy_review
from colorstats.analyze import prep
from colorstats.review_html import file_uri, image_tag, uri_sha, validate_html


def mpo(tmp_path, orientation=None, frames=2):
    first = Image.new("RGB", (320, 256), "red")
    ImageDraw.Draw(first).rectangle((10, 20, 60, 90), fill="yellow")
    others = [Image.new("RGB", (64, 48), "blue"), Image.new("RGB", (96, 80), "green")]
    options = {}
    if orientation is not None:
        exif = Image.Exif()
        exif[274] = orientation
        options["exif"] = exif
    path = tmp_path / "source.mpo"
    first.save(path, format="MPO", save_all=True, append_images=others[:frames - 1], **options)
    return path


@pytest.mark.parametrize("orientation", [None, 1])
@pytest.mark.parametrize("frames", [2, 3])
def test_MPO原画像を変更せず先頭フレームがAとprepとCに一致する(tmp_path, orientation, frames):
    path = mpo(tmp_path, orientation, frames)
    raw = path.read_bytes()
    with Image.open(path) as source:
        assert source.format == "MPO" and source.n_frames == frames and source.tell() == 0
        first = source.convert("RGB")
        source.seek(1)
        assert source.size != first.size
    with Image.open(io.BytesIO(image_gate.normalize(raw))) as normalized:
        assert normalized.size == first.size
        assert normalized.tobytes() == first.tobytes()
    inspected = prep._inspect(path)
    assert inspected["sha256"] == hashlib.sha256(raw).hexdigest()
    assert (inspected["width"], inspected["height"]) == first.size
    assert inspected["resized"].tobytes() == first.tobytes()
    encoded = io.BytesIO()
    inspected["resized"].save(encoded, format="JPEG", quality=90, optimize=True)
    privacy_review._check_prep_origin(
        {"max_size": [512, 512], "phash_distance": 6}, raw,
        inspected["sha256"], hashlib.sha256(encoded.getvalue()).hexdigest(),
    )
    uri = file_uri(path)
    assert uri.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(uri.split(",", 1)[1], validate=True) == raw
    assert uri_sha(uri) == inspected["sha256"]
    with Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))) as presented:
        assert presented.tell() == 0 and presented.size == first.size
        assert presented.convert("RGB").tobytes() == first.tobytes()


def test_MPOを含むHTMLも復号とSHAと容量上限を検証する(tmp_path):
    path = mpo(tmp_path)
    raw = path.read_bytes()
    uri = "data:image/jpeg;base64," + base64.b64encode(raw).decode()
    content = mobile.page(['<article id="n1">' + image_tag(uri, "合成MPO", "raw")
                           + '</article>'], 1, 1, 1)
    validate_html(content, [1], style=mobile.STYLE)
    with pytest.raises(ValueError, match="SHA"):
        validate_html(content.replace('data-sha256="', 'data-sha256="bad'),
                      [1], style=mobile.STYLE)
    with pytest.raises(ValueError, match="容量上限"):
        validate_html(content, [1], style=mobile.STYLE, limit=len(content.encode()) - 1)
    with pytest.raises(ValueError, match="MIME"):
        validate_html(content.replace("data:image/jpeg;", "data:image/png;"),
                      [1], style=mobile.STYLE)


@pytest.mark.parametrize("orientation", range(2, 9))
def test_向き補正で入力側と異なりうるMPOは生成と取込みの両方で拒否する(tmp_path, orientation):
    path = mpo(tmp_path, orientation)
    with pytest.raises(ValueError, match="向き"):
        file_uri(path)
    uri = "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()
    content = mobile.page(['<article id="n1">' + image_tag(uri, "向き指定MPO", "raw")
                           + '</article>'], 1, 1, 1)
    with pytest.raises(ValueError, match="向き"):
        validate_html(content, [1], style=mobile.STYLE)
    with Image.open(io.BytesIO(image_gate.normalize(path.read_bytes()))) as normalized:
        inspected = prep._inspect(path)["resized"]
        assert (normalized.size, normalized.tobytes()) != (inspected.size, inspected.tobytes())
