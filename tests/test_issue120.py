"""単体HTMLの提示・送付・返信を、合成画像だけで検証する。"""

import base64
import io
import re
import sys
from pathlib import Path

import numpy as np
import pytest
from bench.issue114 import mobile
from PIL import Image

from colorstats.review_html import file_uri, validate_html


def test_取得画像のbyteと解像度を変えずに提示する(tmp_path):
    path = tmp_path / "source.jpg"
    Image.new("RGB", (1600, 1000), "blue").save(path)
    uri = file_uri(path)
    raw = base64.b64decode(uri.split(",", 1)[1], validate=True)
    assert raw == path.read_bytes()
    with Image.open(io.BytesIO(raw)) as image:
        assert image.size == (1600, 1000)
    path = tmp_path / "source.gif"
    Image.new("RGB", (2, 2)).save(path)
    with pytest.raises(ValueError, match="PNG/JPEG"):
        file_uri(path)


def test_写真背景も復号し座標を維持したmaskと輪郭を検査する():
    photo = mobile.jpeg(Image.new("RGB", (30, 20), "blue"))
    mask = np.zeros((20, 30), dtype=bool)
    mask[5:10, 8:18] = True
    card = (f'<article id="n1" style="--photo:url(\'{photo}\')" '
            f'data-photo-sha256="{mobile._uri_sha(photo)}">'
            + mobile.mask_section("sky", mask, (30, 20), number=1,
                                  kind="exclusion", pattern="dash") + '</article>')
    content = mobile.page([card], 1, 1, 1)
    validate_html(content, [1], style=mobile.STYLE)
    for uri in re.findall(r'src="([^"]+)"', content):
        with Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))) as image:
            assert image.size == (30, 20)
    with pytest.raises(ValueError, match="SHA"):
        validate_html(content.replace('data-photo-sha256="', 'data-photo-sha256="bad'),
                      [1], style=mobile.STYLE)


@pytest.mark.parametrize("element", [
    '<img src="https://example.invalid/image.png">',
    '<script>alert(1)</script>', '<link href="style.css">',
    '<iframe src="file:///private.html"></iframe>',
    '<img srcset="remote.png 2x">', '<div style="background:url(remote.png)"></div>',
])
def test_外部参照や実行可能要素を送付HTMLに含めない(element):
    content = mobile.page(['<article id="n1">' + element + '</article>'], 1, 1, 1)
    with pytest.raises(ValueError):
        validate_html(content, [1], style=mobile.STYLE)


@pytest.mark.parametrize("action", [mobile.build, mobile.share])
def test_公開リポジトリ内へ画像入り提示物を作らない(action):
    output = Path(mobile.__file__).resolve().parents[2] / "private-review"
    with pytest.raises(ValueError, match="公開リポジトリ外"):
        if action is mobile.build:
            action(None, None, None, output, None)
        else:
            action(None, None, output)


def test_返信の個別IDや所見を公開リポジトリ内へ保存しない(monkeypatch):
    output = Path(mobile.__file__).resolve().parents[2] / "review-result.json"
    monkeypatch.setattr(sys, "argv", ["mobile", "reply", "--execution", "unused",
                                     "--output", str(output)])
    with pytest.raises(ValueError, match="公開リポジトリ外"):
        mobile.main()
    assert not output.exists()
