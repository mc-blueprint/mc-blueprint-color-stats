"""確認ページの画像描画と、外部参照を許さない検査。"""

import base64
import hashlib
import html
import io
import re
from html.parser import HTMLParser

import numpy as np
from PIL import Image, ImageFilter

TRIAL_STYLE = """body{margin:auto;padding:12px;max-width:900px;font:16px sans-serif}
*{box-sizing:border-box}img{display:block;width:100%;height:auto}
article{border-top:2px solid #777;padding:12px 0}p{line-height:1.6}
.comparison-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
figure{margin:0}figcaption{min-height:2.5em}.photo{background-image:var(--photo);
background-size:100% 100%;background-repeat:no-repeat}details{border:1px solid #aaa;padding:8px}
table{border-collapse:collapse;width:100%}th,td{border:1px solid #aaa;padding:6px}
section{margin:12px 0}small{font-size:.8em}"""


def jpeg(image):
    """長辺800px以内のJPEGをdata URI用に符号化する。"""
    image = image.convert("RGB")
    image.thumbnail((800, 800), Image.Resampling.LANCZOS)
    stream = io.BytesIO()
    image.save(stream, format="JPEG", quality=78, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(stream.getvalue()).decode()


def mask_uri(mask, size):
    """座標を維持した単独maskのdata URIを返す。"""
    values = np.asarray(mask)
    if values.shape != (size[1], size[0]) or not np.isin(values, [False, True, 0, 255]).all():
        raise ValueError("maskの座標・二値値が不正です")
    image = Image.fromarray((values != 0).astype("uint8") * 255, mode="L")
    stream = io.BytesIO()
    image.save(stream, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()


def outline_uri(mask, size, *, pattern="solid", transparent=False):
    """元座標の輪郭を別画像にし、役割ごとの線種で区別する。"""
    values = np.asarray(mask) != 0
    if values.shape != (size[1], size[0]):
        raise ValueError("輪郭maskの寸法が一致しません")
    source = Image.fromarray(values.astype("uint8") * 255, mode="L")
    outer = np.asarray(source.filter(ImageFilter.MaxFilter(7 if transparent else 3))) != 0
    edge = outer & ~values
    if pattern == "dash":
        edge[1::4] = False
        edge[3::4] = False
    elif pattern == "dot":
        edge[::3, ::3] = False
    elif pattern == "dashdot":
        edge[1::4] = False
        edge[3::4, ::3] = False
    elif pattern != "solid":
        raise ValueError("未対応の輪郭線種です")
    if transparent:
        pixels = np.zeros((*edge.shape, 4), dtype="uint8")
        pixels[edge] = [255, 96, 0, 255]
        result = Image.fromarray(pixels, mode="RGBA")
    else:
        result = Image.fromarray(np.where(edge, 0, 255).astype("uint8"), mode="L")
    stream = io.BytesIO()
    result.save(stream, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()


def uri_sha(uri):
    return hashlib.sha256(base64.b64decode(uri.split(",", 1)[1])).hexdigest()


def image_tag(uri, alt, style):
    return (
        f'<img class="{style}" alt="{html.escape(alt)}" src="{uri}" '
        f'data-sha256="{uri_sha(uri)}" loading="lazy">'
    )


class _PageCheck(HTMLParser):
    def __init__(self):
        super().__init__()
        self.numbers = []
        self.images = set()
        self.styles = []
        self.inline_styles = []
        self.in_style = False

    def handle_starttag(self, tag, attrs):
        if len({key for key, _ in attrs}) != len(attrs):
            raise ValueError("重複したHTML属性は受け付けません")
        attrs = dict(attrs)
        if (
            tag in {"script", "iframe", "object", "embed", "link", "base", "svg", "math"}
            or any(
                k.startswith("on") or k in {"srcset", "poster", "action", "formaction"}
                for k in attrs
            )
            or any(k in {"src", "href"} and not (tag == "img" and k == "src") for k in attrs)
            or (tag == "meta" and attrs.get("http-equiv", "").strip().lower() == "refresh")
        ):
            raise ValueError("HTMLに外部参照または実行可能な要素があります")
        if tag == "article":
            match = re.fullmatch(r"n([1-9][0-9]*)", attrs.get("id", ""))
            if match is None:
                raise ValueError("番号がありません")
            self.numbers.append(int(match[1]))
        if tag == "img":
            uri = attrs.get("src", "")
            if not re.fullmatch(r"data:image/(?:jpeg|png);base64,[A-Za-z0-9+/=]+", uri):
                raise ValueError("埋込PNG/JPEG以外の画像です")
            raw = base64.b64decode(uri.split(",", 1)[1], validate=True)
            if hashlib.sha256(raw).hexdigest() != attrs.get("data-sha256"):
                raise ValueError("埋込画像SHAが一致しません")
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in {"PNG", "JPEG"}:
                    raise ValueError("埋込画像の実形式が不正です")
                image.verify()
            self.images.add(uri)
        if "style" in attrs:
            self.inline_styles.append(attrs["style"])
        if tag == "style":
            self.in_style = True

    def handle_endtag(self, tag):
        if tag == "style":
            self.in_style = False

    def handle_data(self, data):
        if self.in_style:
            self.styles.append(data)


def validate_html(content, numbers, *, limit=12_500_000):
    """試行用HTMLの実byte上限・番号・埋込SHA・外部参照0を検査する。"""
    if len(content.encode()) > limit:
        raise ValueError("HTMLが容量上限を超えました")
    parser = _PageCheck()
    parser.feed(content)
    parser.close()
    if parser.numbers != list(numbers):
        raise ValueError("ページの連番が一致しません")
    if any(style != TRIAL_STYLE for style in parser.styles):
        raise ValueError("生成ページの固定CSSが必要です")
    for style in parser.inline_styles:
        match = re.fullmatch(
            r"--photo:url\('(?P<uri>data:image/(?:jpeg|png);base64,[A-Za-z0-9+/=]+)'\)", style
        )
        if match is None or match["uri"] not in parser.images:
            raise ValueError("写真用の埋込画像指定が必要です")
