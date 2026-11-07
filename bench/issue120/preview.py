"""#118の非公開smoke成果物から、本番未登録の目視プレビューを作る。"""

import argparse
import base64
import hashlib
import html
import json
import random
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
from bench.issue114.mobile import jpeg, mask_uri, outline_uri
from PIL import Image

MAX_BYTES = 25_000_000


class PreviewParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.articles = 0
        self.images = 0
        self.external = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "article":
            self.articles += 1
        if tag == "img":
            self.images += 1
            source = values.get("src", "")
            prefix = "data:image/"
            if not source.startswith(prefix) or ";base64," not in source:
                self.external.append(source[:80])
            else:
                base64.b64decode(source.split(",", 1)[1], validate=True)
        for attribute in ("src", "href"):
            value = values.get(attribute)
            if value and not value.startswith(("data:", "#")):
                self.external.append(value[:80])


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def data_uri_image(path):
    with Image.open(path) as image:
        return jpeg(image)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=120)
    args = parser.parse_args()

    artifacts = args.artifacts
    manifest = json.loads((artifacts / "inputs-20/selection.json").read_text())
    assets = sorted(manifest["assets"], key=lambda row: row["file"])
    if len(assets) != 20:
        raise ValueError("inputs-20の固定manifestが20件ではありません")
    selected = sorted(random.Random(args.seed).sample(assets, 10), key=lambda row: row["file"])

    cards = []
    for number, asset in enumerate(selected, 1):
        image_path = artifacts / "inputs-20" / asset["file"]
        if sha256(image_path) != asset["input_sha256"]:
            raise ValueError("選択画像のSHA-256がmanifestと一致しません")
        sample = artifacts / "run-20" / Path(asset["file"]).stem
        segment_path = sample / "segment.json"
        segment = json.loads(segment_path.read_text(encoding="utf-8"))
        policy = segment["region_policy"]
        if policy["input_sha256"] != asset["input_sha256"]:
            raise ValueError("region-policyの入力hashが選択画像と一致しません")

        with Image.open(image_path) as image:
            size = image.size
            raw_uri = jpeg(image)
        figures = [f'''<figure><figcaption>入力画像</figcaption>
<img class="raw" alt="番号{number} 入力画像" src="{raw_uri}"></figure>''']
        masks = [*(('有効領域', key, value) for key, value in policy["roles"].items()),
                 *(('除外領域', key, value) for key, value in policy["exclusions"].items())]
        for category, label, record in sorted(masks, key=lambda item: (item[0], item[1])):
            mask_path = sample / Path(record["path"]).name
            if sha256(mask_path) != record["sha256"]:
                raise ValueError("maskのSHA-256がregion-policyと一致しません")
            with Image.open(mask_path) as image:
                mask = np.asarray(image.convert("L")) != 0
            if mask.shape != (size[1], size[0]):
                raise ValueError("maskと入力画像の座標が一致しません")
            safe_label = html.escape(label)
            figures.append(f'''<figure><figcaption>{category}mask：{safe_label}</figcaption>
<img class="mask" alt="番号{number} {safe_label} mask" src="{mask_uri(mask, size)}"></figure>
<figure><figcaption>{category}輪郭：{safe_label}</figcaption>
<img class="outline" alt="番号{number} {safe_label} 輪郭"
src="{outline_uri(mask, size, pattern='dash' if category == '有効領域' else 'dot')}"></figure>''')
        cards.append(f'<article><h2>番号 {number}</h2>{"".join(figures)}</article>')

    document = f'''<!doctype html><html lang="ja"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy"
content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">
<title>Issue #120 表示プレビュー</title>
<style>
body{{margin:0 auto;padding:12px;max-width:800px;font:16px sans-serif}}
img{{display:block;max-width:100%;height:auto;margin:8px 0}}
figure{{margin:0 0 16px}}article{{border-top:2px solid #777;padding:12px 0}}
.raw{{border:3px solid #222}}.mask{{border:3px dashed #176b35;image-rendering:pixelated}}
.outline{{border:3px dotted #174ea6;image-rendering:pixelated}}
</style>
<h1>プレビュー（本番未登録）</h1>
<p>#118 parents-v2 の非公開試運転成果物20枚から、seed {args.seed}で選んだ10枚です。
原画像、region-policy-v1有効mask、除外maskを表示します。DB接続・本番登録は行っていません。</p>
{"".join(cards)}</html>'''
    encoded = document.encode("utf-8")
    if len(encoded) > MAX_BYTES:
        raise ValueError("プレビューHTMLが25MBを超えています")
    validator = PreviewParser()
    validator.feed(document)
    if validator.articles != 10 or validator.images == 0 or validator.external:
        raise ValueError("HTMLの件数、画像data URI、外部参照の検証に失敗しました")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encoded)
    args.output.chmod(0o600)
    print(json.dumps({"bytes": len(encoded), "samples": len(selected),
                      "embedded_images": validator.images, "external_references": 0,
                      "sha256": hashlib.sha256(encoded).hexdigest()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
