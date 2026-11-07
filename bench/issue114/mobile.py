"""必須目視サンプルを単体HTMLにし、番号付きの会話返信を既存取込み形式へ変換する。"""

import argparse
import base64
import hashlib
import html
import io
import json
import os
import socket
from pathlib import Path
from uuid import UUID

import numpy as np
import yaml
from bench.issue114.privacy import digest, import_reviews, save
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from colorstats import retention
from colorstats.schema.models import Region

LIMIT = 25_000_000
REASONS = {"person_not_detected": "人物検出なし", "person_masked": "人物maskあり",
           "subject_ambiguous": "主体混在", "subject_unresolved": "主体不明",
           "person_over_limit": "人物面積超過"}
STYLE = """body{margin:0 auto;padding:12px;max-width:800px;font:16px sans-serif;
overflow-wrap:anywhere;box-sizing:border-box}*{box-sizing:border-box}
img{display:block;max-width:100%;height:auto;margin:8px 0}article{border-top:2px solid #777;
padding:12px 0}p{line-height:1.6}h2{font-size:1.3rem}figure{margin:0}figcaption{font-weight:bold}"""


def jpeg(image):
    """長辺800px以内のJPEGをdata URI用に符号化する。"""
    image = image.convert("RGB")
    image.thumbnail((800, 800), Image.Resampling.LANCZOS)
    stream = io.BytesIO()
    image.save(stream, format="JPEG", quality=78, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(stream.getvalue()).decode()


def overlay(image, regions, person, building, terrain):
    """建物は緑、地形は青、人物は赤で重ね、人物を最前面にする。"""
    image = image.convert("RGB")
    for labels, color in ((building, "lime"), (terrain, "dodgerblue")):
        union = np.zeros((image.height, image.width), dtype=bool)
        for label, path in regions:
            if label in labels:
                with Image.open(path) as mask:
                    values = np.asarray(mask.convert("L")) != 0
                if values.shape != union.shape:
                    raise ValueError("主体maskの寸法が一致しません")
                union |= values
        tinted = Image.blend(image, Image.new("RGB", image.size, color), .3)
        image = Image.composite(tinted, image, Image.fromarray(union.astype("uint8") * 255))
    with Image.open(person) as mask:
        if mask.size != image.size:
            raise ValueError("人物maskの寸法が一致しません")
        tinted = Image.blend(image, Image.new("RGB", image.size, "red"), .65)
        return Image.composite(tinted, image, mask.convert("L"))


def page(cards, first, last, total):
    return f'''<!doctype html><html lang="ja"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy"
content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">
<title>#114 目視確認 {first}–{last}</title><style>{STYLE}</style>
<h1>#114 目視確認 {first}–{last}／全{total}枚</h1>
<p>全ファイルの全番号を確認してください。人物の見落とし、赤い人物maskの不足、
主体が建物・地形でない、緑／青の主体領域や自動subjectの誤りがあれば、
チャットへ「問題あり：番号と理由」を返信してください。
全件確認後は「全{total}枚確認済み。問題なし」または
「全{total}枚確認済み。問題あり：7 人物の見落とし、…」と返信します。
途中の確認は完了扱いにしません。JSONの保存・送付は不要です。</p>
<p>上：取得画像。下：解析画像に人物=赤、建物=緑、地形=青を重ねたもの。
重複領域は青が緑に重なります。人物率は検出値と2px膨張後の除外率を表示します。
「目視待ち」の画像は確認しても自動で採用へ変更しません。</p>
{''.join(cards)}</html>'''


def write_pages(cards, output, limit=LIMIT):
    """UTF-8の実byte数で上限を守り、通し番号を維持して分割する。"""
    groups, current, first = [], [], 1
    sizes = [len(card.encode()) for card in cards]
    total = sum(sizes)
    if len(page([], 1, len(cards), len(cards)).encode()) + total > limit:
        candidates, prefix = [], 0
        for cut, size in enumerate(sizes[:-1], 1):
            prefix += size
            left = prefix + len(page([], 1, cut, len(cards)).encode())
            right = total - prefix + len(page([], cut + 1, len(cards), len(cards)).encode())
            if max(left, right) <= limit:
                candidates.append((abs(left - right), cut))
        if candidates:
            cut = min(candidates)[1]
            groups = [(1, cut, cards[:cut]), (cut + 1, len(cards), cards[cut:])]
    for number, card in enumerate([] if groups else cards, 1):
        if len(page(current + [card], first, number, len(cards)).encode()) > limit:
            if not current:
                raise ValueError("1画像分のHTMLが容量上限を超えました")
            groups.append((first, number - 1, current))
            current, first = [], number
        current.append(card)
    if current:
        groups.append((first, len(cards), current))
    files = []
    for part, (first, last, group) in enumerate(groups, 1):
        content = page(group, first, last, len(cards)).encode()
        if len(content) > limit:
            raise ValueError("HTMLが容量上限を超えました")
        path = output / f"review-{part:02}.html"
        with path.open("xb") as stream:
            stream.write(content)
        path.chmod(0o600)
        files.append({"file": path.name, "bytes": len(content), "first": first, "last": last,
                      "sha256": digest(path)})
    return files


def build(db, bundle, execution, output, taxonomy, *, host=None):
    """保持ロック下で利用可否を確認し、画像入りHTMLと番号表を保持登録する。"""
    manifest = json.loads((bundle / "manifest.json").read_text())
    created = False
    try:
        with Session(db) as session, session.begin():
            retention.lock(session)
            for aid in manifest["required_ids"]:
                retention.assert_usable(session, UUID(aid), images=True)
            output.mkdir(mode=0o700, exist_ok=False)
            created = True
            _build(session, manifest, bundle, execution, output, taxonomy,
                   host or socket.gethostname())
    except BaseException:
        if created:
            for path in output.iterdir():
                path.unlink()
            output.rmdir()
        raise


def _build(session, manifest, bundle, execution, output, taxonomy, host):
    if manifest["decisions_sha256"] != digest(execution / "privacy-decisions.json"):
        raise ValueError("閲覧manifestと自動判定が一致しません")
    decisions = {row["asset_id"]: row for row in json.loads(
        (execution / "privacy-decisions.json").read_text())}
    ids = sorted(manifest["required_ids"])
    parts = yaml.safe_load((taxonomy / "parts.yaml").read_text())
    building = {label for group, labels in parts["groups"].items() if group != "context"
                for label in labels}
    terrain = set(yaml.safe_load((taxonomy / "terrain.yaml").read_text())["labels"])
    regions = {}
    for region in session.scalars(select(Region).where(
        Region.processing_run_id.in_([UUID(decisions[aid]["region_run_id"]) for aid in ids]),
    )):
        regions.setdefault(str(region.asset_id), []).append((region.label, region.mask_path))
    cards, rows = [], []
    for number, aid in enumerate(ids, 1):
        row = decisions[aid]
        labels = (["無作為"] if aid in manifest["random_ids"] else [])
        labels += ["閾値付近"] if aid in manifest["boundary_ids"] else []
        with Image.open(bundle / "images" / f"{aid}-raw.png") as raw:
            raw_uri = jpeg(raw)
        if digest(row["input_path"]) != row["input_sha256"] or digest(
                row["mask_path"]) != row["mask_sha256"]:
            raise ValueError("固定した解析画像・人物maskが変わっています")
        with Image.open(row["input_path"]) as image:
            view = overlay(image, regions.get(aid, []), row["mask_path"], building, terrain)
            overlay_uri = jpeg(view)
        decision = "採用" if row["decision"] == "accepted" else "目視待ち"
        subject = {"building": "建物", "terrain": "地形", None: "未確定"}[row["subject"]]
        cards.append(f'''<article id="n{number}"><h2>番号 {number}：{'・'.join(labels)}</h2>
<p>自動判定：{decision}／{html.escape(REASONS[row['reason']])}。
人物率 {row['person_ratio']:.4%}（膨張後 {row['mask_ratio']:.4%}）、subject：{subject}。</p>
<figure><figcaption>取得画像</figcaption>
<img alt="番号{number} 取得画像" src="{raw_uri}" loading="lazy"></figure>
<figure><figcaption>人物mask・主体領域</figcaption>
<img alt="番号{number} 人物と主体の重畳" src="{overlay_uri}" loading="lazy"></figure></article>''')
        rows.append({"number": number, "asset_id": aid, "groups": labels,
                     **{key: row[key] for key in ("decision", "subject", "reason",
                                                "person_ratio", "mask_ratio")}})
    files = write_pages(cards, output)
    save(output / "number-map.json", {
        "format": "issue114-mobile-v1", "review_manifest_sha256": digest(bundle / "manifest.json"),
        "decisions_sha256": manifest["decisions_sha256"], "rows": rows, "files": files,
    })
    for item in files:
        for row in rows[item["first"] - 1:item["last"]]:
            retention.register_file(session, UUID(row["asset_id"]), host,
                                    output / item["file"], "image_bundle")
    for aid in ids:
        retention.register_file(session, UUID(aid), host,
                                output / "number-map.json", "image_bundle")
    print(json.dumps({"total": len(rows), "files": files}, ensure_ascii=False))


def reply_reviews(mapping, manifest, decisions_sha256, reply):
    """全提示画像の確認済み返信だけを変換する。未提示画像は人の確認にしない。"""
    if (mapping["format"] != "issue114-mobile-v1"
            or mapping["decisions_sha256"] != decisions_sha256
            or mapping["review_manifest_sha256"] != digest(manifest)):
        raise ValueError("番号表と固定した閲覧対象が一致しません")
    review = json.loads(manifest.read_text())
    required = set(review["required_ids"])
    rows = mapping["rows"]
    if ([row["number"] for row in rows] != list(range(1, len(rows) + 1))
            or [row["asset_id"] for row in rows] != sorted(required)):
        raise ValueError("番号表の対象・連番が一致しません")
    originals = {row["asset_id"]: row for row in review["rows"]}
    for row in rows:
        if any(row[key] != value for key, value in originals[row["asset_id"]].items()):
            raise ValueError("番号表の自動判定が閲覧原本と一致しません")
    if reply.get("all_reviewed") is not True or not reply.get("reply_text", "").strip():
        raise ValueError("全提示画像の確認済み返信が必要です")
    problems = {}
    for problem in reply["problems"]:
        number = problem["number"]
        if (type(number) is not int or number < 1 or number > len(rows)
                or number in problems or not problem["reason"].strip()):
            raise ValueError("問題番号が範囲外・重複、または理由が空です")
        problems[number] = problem["reason"].strip()
    return {"reviewer": "ユーザー", "confirm_no_errors": not problems,
            "decisions_sha256": decisions_sha256, "chat_reply": reply["reply_text"],
            "number_map_sha256": hashlib.sha256(
                json.dumps(mapping, sort_keys=True).encode()).hexdigest(),
            "rows": [{"asset_id": row["asset_id"],
                      "decision": "pending" if row["number"] in problems else "same",
                      "subject": row["subject"], "error_found": row["number"] in problems,
                      "note": problems.get(row["number"], "会話で提示画像の確認済み・問題なし")}
                     for row in rows]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "reply"))
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--taxonomy", type=Path)
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--host", help="保持台帳へ登録する生成先host（省略時は実行host）")
    args = parser.parse_args()
    os.umask(0o077)
    if args.action == "reply":
        data = reply_reviews(json.loads(args.mapping.read_text()),
                             args.execution / "review-manifest.json",
                             digest(args.execution / "privacy-decisions.json"),
                             json.loads(args.input.read_text()))
        save(args.output, data)
        if not args.apply:
            print("番号返信を変換しました。DB接続・書込みなし。")
            return
    from bench.issue105.production import engine

    db = engine(False)
    try:
        if args.action == "build":
            build(db, args.bundle, args.execution, args.output, args.taxonomy, host=args.host)
        else:
            import_reviews(db, args.execution, args.output)
    finally:
        db.dispose()


if __name__ == "__main__":
    main()
