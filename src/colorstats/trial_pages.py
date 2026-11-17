"""固定したtrial出力だけを、番号付きの非公開比較HTMLへ変換する。"""

import random
from pathlib import Path

import numpy as np
from PIL import Image

from colorstats.review_html import TRIAL_STYLE as STYLE
from colorstats.review_html import image_tag, jpeg, outline_uri, validate_html
from colorstats.trial_inputs import SEED, add_files, encoded, sha, stamp, write_private
from colorstats.trial_results import PARTS, load_mask, read_results

LIMIT = 12_500_000

SCENE_NAMES = {
    "single": "屋外の建物1棟",
    "interior": "屋内",
    "group": "建物群・街並み",
    "gate": "門",
    "closeup": "部位の接写",
    "terrain": "地形",
    "unknown": "不明",
    "unsupported": "この案では場面を判定しません",
}
STATE_NAMES = {
    "success": "出力あり",
    "missing": "見つかりませんでした",
    "failed": "処理失敗",
    "rejected": "確認できず出力を止めました",
    "truncated": "途中で回答が切れました",
}


def _section(part, mask, size, photo, number, label):
    name, definition = PARTS[part]
    if mask.all():
        definition += " 写真全体が選ばれています。"
    elif not mask.any():
        definition += " 選ばれた場所がありません。"
    line = image_tag(
        outline_uri(mask, size, transparent=True), f"番号{number} 案{label} {name}の輪郭", "outline"
    )
    return f"""<section><h4>{name}</h4><p>{definition}</p><div class="comparison-grid">
<figure><figcaption>もとの写真</figcaption>{photo}</figure>
<figure><figcaption>写真＋{name}の輪郭線</figcaption><div class="photo">{line}</div>
</figure></div></section>"""


def _card(root, image, outputs):
    number = image["number"]
    with Image.open(root / image["input"]["file"]) as source:
        uri = jpeg(source)
    photo = image_tag(uri, f"番号{number} もとの写真", "original")
    order = list("ABCDE")
    random.Random(SEED + number).shuffle(order)
    parts = [f'<article id="n{number}" style="--photo:url(\'{uri}\')"><h2>番号{number}</h2>{photo}']
    for label, config in zip("ABCDE", order, strict=True):
        row = outputs[config]
        parts.append(
            f"<section><h3>案{label}</h3><p>{STATE_NAMES[row['status']]}／"
            f"{SCENE_NAMES[row['scene']]}</p>"
        )
        for detail, labels in [
            (False, ("wall", "roof")),
            (True, ("window", "window_glass", "window_frame", "door")),
        ]:
            if detail:
                parts.append("<details><summary>窓・扉の細かな部分を見る</summary>")
            for part in labels:
                found = [r for r in row["regions"] if r["part"] == part]
                if not found:
                    parts.append(f"<p>{PARTS[part][0]}：出力なし（正しさは未確認）</p>")
                    continue
                mask = np.zeros(tuple(reversed(row["size"])), dtype=bool)
                for region in found:
                    mask |= load_mask(root, region["mask"], row["size"])
                parts.append(_section(part, mask, row["size"], photo, number, label))
            if detail:
                parts.append("</details>")
        parts.append("</section>")
    parts.append("</article>")
    return "".join(parts), {
        "number": number,
        "trial_id": image["trial_id"],
        "split": image["split"],
        "positions": dict(zip("ABCDE", order, strict=True)),
    }


def page(cards, split, synthetic=False):
    phase = "最初の6枚" if split == "tune" else "続きの24枚"
    warning = (
        "合成画像による動作確認です。実写真や実モデルの品質を示すものではありません。"
        if synthetic
        else ""
    )
    legend = "".join(
        f"<tr><th>{name}</th><td>{definition}</td></tr>" for name, definition in PARTS.values()
    )
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy"
content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">
<title>写真の比較 {phase}</title><style>{STYLE}</style></head><body>
<h1>写真の比較：{phase}</h1><p>{warning}</p>
<p>番号ごとに、写真と線を比べてください。線のない場所の色は隠していません。
案A～Eの並びは番号ごとに違います。同じ文字でも別の番号では同じ方式を指しません。</p>
<p>まず最初の6枚を確認し、どれも使えなければ残りの確認を中止できます。
続きのファイルを作ったことだけで、確認を終えたとは扱いません。</p>
<p>返信は「1: A,C」のように使えそうな案を複数書くか、「1: なし」「1: 不明」と書いてください。
明らかに違うところがあれば「1: Bの屋根」のように追記してください。
写っていない部分は「対象なし」としてください。輪郭の修正は不要です。
案の番号だけでは、別の確認ページへの承認に使いません。</p>
<p>壁・屋根・窓全体・扉を比べます。ガラスと枠は細部の確認用です。
窓全体にはガラスと枠が含まれるため、それらの重なりは間違いとは限りません。
出力がないことや、案どうしが似ていることは、正しさの証明にはなりません。</p>
<table><caption>部分の名前と説明</caption>{legend}</table>
{"".join(cards)}</body></html>"""


def build_pages(result_root, *, limit=LIMIT, now=None):
    """受領済み150結果を照合し、6枚と24枚を混ぜずbyte上限内で分割する。

    ページSHA・入力manifest SHA・結果SHA・構成SHA・位置表を私有番号表へ結ぶ。
    本番提示登録や旧返信取込みは呼び出さない。既存ページは上書きしない。
    """
    root = Path(result_root)
    manifest, _, results = read_results(root, now=now)
    if not 0 < limit <= LIMIT:
        raise ValueError("HTMLの上限は12,500,000 byte以下です")
    if (root / "pages").exists() or (root / "number-map.json").exists():
        raise ValueError("既存の比較ページは変更しません")
    outputs = {(r["trial_id"], r["configuration_id"]): r for r in results}
    mapping, files, blobs = [], [], {}
    for split in ("tune", "confirm"):
        cards, numbers = [], []
        batches = []
        for image in (r for r in manifest["images"] if r["split"] == split):
            card, row = _card(root, image, {c: outputs[image["trial_id"], c] for c in "ABCDE"})
            mapping.append(row)
            if len(page([card], split, manifest["synthetic"]).encode()) > limit:
                raise ValueError("1番号分のHTMLが容量上限を超えました")
            if cards and len(page(cards + [card], split, manifest["synthetic"]).encode()) > limit:
                batches.append((cards, numbers))
                cards, numbers = [], []
            cards.append(card)
            numbers.append(image["number"])
        if cards:
            batches.append((cards, numbers))
        for n, (cards, numbers) in enumerate(batches, 1):
            blob = page(cards, split, manifest["synthetic"]).encode()
            validate_html(blob.decode(), numbers, limit=limit)
            name = f"pages/{split}-{n:02}.html"
            blobs[name] = blob
            files.append(
                {"file": name, "numbers": numbers, "bytes": len(blob), "sha256": sha(blob)}
            )
    table = {
        "version": "trial-pages-v1",
        "manifest_sha256": sha((root / "manifest.json").read_bytes()),
        "results_sha256": sha((root / "results.json").read_bytes()),
        "configurations_sha256": sha((root / "configurations.json").read_bytes()),
        "active_attempts_sha256": sha((root / "active-attempts.json").read_bytes()),
        "rows": mapping,
        "files": files,
    }
    blobs["number-map.json"] = encoded(table)
    expiry = min((r["local_expires_at"] for r in manifest["images"]), key=stamp)
    add_files(
        root,
        [{"file": name, "sha256": sha(blob), "expires_at": expiry} for name, blob in blobs.items()],
    )
    (root / "pages").mkdir(mode=0o700)
    for name, blob in blobs.items():
        write_private(root / name, blob)
    return table
