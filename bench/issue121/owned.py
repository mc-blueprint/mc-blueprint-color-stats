"""私有inventoryから予測に依存しない新旧50枚を固定し、rawのみの単体HTMLを作る。"""

import argparse
import html
import json
import random
from pathlib import Path

from bench.issue73.evaluate import digest, read, write
from bench.issue114.mobile import STYLE, jpeg
from bench.issue120.preview import MAX_BYTES, PreviewParser
from PIL import Image, ImageOps

SEED = 12120261107


def select(inventory, known_ids, known_shas, *, count=50):
    """原画像SHAでcohortをまたいで一意化し、既知画像を除いて固定順から抽出する。

    inventoryは保持・権利確認済みのasset_id/cohort/sha256/input_pathを持つ行。
    同一SHAが両cohortにある場合は旧cohortの代表を使う。予測値は参照しない。
    """
    unique = {}
    known_shas = set(known_shas) | {row["sha256"] for row in inventory
                                    if row["asset_id"] in known_ids}
    for row in sorted(inventory, key=lambda row: (row["cohort"] != "old", row["asset_id"])):
        if row["asset_id"] in known_ids or row["sha256"] in known_shas:
            continue
        unique.setdefault(row["sha256"], row)
    rng = random.Random(SEED)
    selected, counts = [], {}
    for cohort in ("old", "new"):
        eligible = sorted((row for row in unique.values() if row["cohort"] == cohort),
                          key=lambda row: row["asset_id"])
        counts[cohort] = len(eligible)
        first = len(selected)
        selected.extend({**row, "group": "random", "number": first + number}
                        for number, row in enumerate(rng.sample(eligible, count), 1))
    return selected, counts


def freeze(inventory_path, known_path, output):
    """私有inventoryと除外台帳をSHAごと固定する。画像やAPI判定はまだ読まない。"""
    inventory, known = read(inventory_path), read(known_path)
    rows, counts = select(inventory["assets"], set(known["ids"]), set(known["sha256"]))
    selected_shas = {row["sha256"] for row in rows}
    challenge = {}
    for row in sorted(inventory["assets"], key=lambda row: row["asset_id"]):
        if row["asset_id"] in known["challenge_ids"] and row["sha256"] not in selected_shas:
            challenge.setdefault(row["sha256"], row)
    challenge_rows = random.Random(SEED + 1).sample(
        list(challenge.values()), min(10, len(challenge)))
    challenge_rows = [{**row, "group": "challenge", "number": 101 + i}
                      for i, row in enumerate(challenge_rows)]
    result = {"seed": SEED, "inventory_sha256": digest(inventory_path),
              "known_sha256": digest(known_path), "eligible": counts, "rows": rows,
              "random": {"old": 50, "new": 50}, "challenge": challenge_rows,
              "predictions_seen": False, "api_global_batch_already_started": True,
              "limitation": "#117全量判定は先行実行中。抽出はその結果を参照していない。"}
    write(output, result)
    return result


def build(manifest_path, output):
    """固定原画像を照合してrawだけを提示する。採用判定・mask承認・保持登録はしない。"""
    manifest = read(manifest_path)
    cards = []
    for row in manifest["rows"] + manifest["challenge"]:
        path = Path(row["input_path"])
        if digest(path) != row["sha256"]:
            raise ValueError("原画像SHAが抽出前から変更されています")
        with Image.open(path) as image:
            uri = jpeg(ImageOps.exif_transpose(image))
        number = row["number"]
        cohort = "旧cohort" if row["cohort"] == "old" else "新cohort"
        group = "無作為群" if row["group"] == "random" else "challenge群（率の分母から除外）"
        cards.append(f'<article><h2>番号 {number}：{cohort}・{group}</h2>'
                     f'<img class="raw" alt="番号{number} 原画像" src="{uri}"></article>')
    count = len(cards)
    document = f'''<!doctype html><html lang="ja"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy"
content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">
<title>#121 新しい目視確認</title><style>{STYLE}</style>
<h1>#121 新しい目視確認：全{count}枚</h1>
<p>旧・新cohort各50枚。既知試験・同一SHAを除外しseed {manifest['seed']}で固定しました。
番号101以降は既知の人物・対象等の失敗例から別抽出したchallenge群で、無作為率に混ぜません。
原画像だけの確認です。自動判定とmaskはまだ表示していません。画素正解の評価ではありません。</p>
<p>全番号の人物、対象、主体、白黒、暗所、混在を確認してください。建築部位の接写は対象です。
人物あり・不明、暗所・混在は保留、白黒は除外します。</p>
<p>「全{count}枚確認済み。問題なし」または「全{count}枚確認済み。
問題あり：7 人物、85 白黒、…」と返信してください。
問題なしは人物なし・対象が建築または地形・明るいカラー画像を意味します。
各番号の主体（建築／地形／混在／その他／不明）も番号とともに返信してください。
未確認・不明は明記し、確認済みと扱いません。保留の画像は自動採用しません。</p>
<p>約100枚で人物見落とし0件でも言えるのは約3%を超えないまでです。
実際の採用分母とcohortごとの区間は自動判定完了後に別途計算します。</p>
<p>固定manifest SHA-256：{html.escape(digest(manifest_path))}</p>
{''.join(cards)}</html>'''
    encoded = document.encode()
    parser = PreviewParser()
    parser.feed(document)
    if len(encoded) > MAX_BYTES or parser.external or parser.articles != count:
        raise ValueError("単体HTMLの件数・外部参照・25MB上限の検証に失敗しました")
    with output.open("xb") as stream:
        stream.write(encoded)
    output.chmod(0o600)
    return {"samples": count, "bytes": len(encoded), "sha256": digest(output),
            "manifest_sha256": digest(manifest_path), "external_references": 0,
            "predictions_presented": False, "retention_registered": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["freeze", "html"])
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--known", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "freeze":
        freeze(args.inventory, args.known, args.output)
    else:
        print(json.dumps(build(args.manifest, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
