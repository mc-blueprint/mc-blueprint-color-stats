"""既存の下書きからモデル判定用の一覧画像・バッチを作る。判定はしない。"""

import argparse
import csv
import hashlib
import json
import math
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import jsonschema
import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageFont


def _save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
                    encoding="utf-8")


def draft_mask(shape, size):
    """CVAT行優先RLEをannotation_sizeのbool配列へ復元する。不正RLEは拒否する。"""
    width, height = size
    left, top, w, h = (int(shape[key]) for key in ("left", "top", "width", "height"))
    counts = [int(value.strip()) for value in shape["rle"].split(",")]
    if (min(left, top) < 0 or min(w, h) < 1 or left + w > width or top + h > height
            or min(counts) < 0 or sum(counts) != w * h):
        raise ValueError("RLEまたはmask範囲が不正です")
    mask = np.zeros((height, width), dtype=bool)
    mask[top:top + h, left:left + w] = np.repeat(
        np.arange(len(counts)) % 2, counts).reshape(h, w).astype(bool)
    return mask


def validate_judgment(result, inputs, schema):
    """schemaに加え、入力の全画像・全draft_idとの一対一対応を検証する。"""
    jsonschema.Draft202012Validator(schema).validate(result)
    if result["batch_id"] != inputs["batch_id"]:
        raise ValueError("batch_idが入力と異なります")
    expected = {image["asset_id"]: {r["draft_id"] for r in image["regions"]}
                for image in inputs["images"]}
    actual = {}
    for image in result["images"]:
        aid = image["asset_id"]
        ids = [r["draft_id"] for r in image["regions"]]
        if aid in actual or len(ids) != len(set(ids)):
            raise ValueError("画像またはdraft_idが重複しています")
        actual[aid] = set(ids)
    if actual != expected:
        raise ValueError("判定に画像・領域の過不足があります")


def summarize_judgments(inputs, judgments, repeated, selection):
    """検証済み初回結果と再判定を集計する。selectionはasset_idをキーにした行辞書。

    領域はdraft_id単位、見落としは画像ごとのlabel集合で数える。分母0の率はnull。
    同定は初回結果を採用し、既存IDとの比較は名称の翻訳ではなく同一群の構成で行う。
    戻り値は集計と、根拠・既存候補を保持した同定結果。入力は変更しない。
    """
    verdicts = ("correct", "wrong_label", "spill", "not_present")

    def breakdown(regions):
        counts = Counter(r["verdict"] for r in regions)
        total = sum(counts.values())
        return {"regions": total, "counts": {v: counts[v] for v in verdicts},
                "rates": {v: counts[v] / total if total else None for v in verdicts}}

    def agreement(matches, total):
        return {"matches": matches, "total": total,
                "rate": matches / total if total else None}

    labels, domains = defaultdict(list), defaultdict(list)
    missed, images, all_regions = Counter(), {}, []
    names, candidates = defaultdict(list), defaultdict(list)
    for aid, result in judgments.items():
        row = selection[aid]
        source = {r["draft_id"]: r for r in inputs[aid]["regions"]}
        regions = result["regions"]
        all_regions.extend(regions)
        domains[row["domain"]].extend(regions)
        for region in regions:
            labels[source[region["draft_id"]]["label"]].append(region)
        missed_labels = sorted({p["label"] for p in result["missed_major_parts"]})
        missed.update(missed_labels)
        images[aid] = {"domain": row["domain"], "stratum": row["stratum"],
                       **breakdown(regions), "missed_major_parts": missed_labels}
        if result["building_name"] is not None:
            names[result["building_name"]].append(aid)
        if row["building_id"]:
            candidates[row["building_id"]].append(aid)

    comparisons = {}
    for aid, repeat in repeated.items():
        first = judgments[aid]
        before = {r["draft_id"]: r["verdict"] for r in first["regions"]}
        after = {r["draft_id"]: r["verdict"] for r in repeat["regions"]}
        if before.keys() != after.keys():
            raise ValueError("二重判定のdraft_idが一致しません")
        comparisons[aid] = {
            "verdict": agreement(sum(before[k] == after[k] for k in before), len(before)),
            "missed_major_parts_equal": ({p["label"] for p in first["missed_major_parts"]}
                                         == {p["label"] for p in repeat["missed_major_parts"]}),
            "building_name_equal": first["building_name"] == repeat["building_name"],
        }
    repeat_summary = {
        "verdict": agreement(sum(c["verdict"]["matches"] for c in comparisons.values()),
                             sum(c["verdict"]["total"] for c in comparisons.values())),
        "missed_major_parts": agreement(
            sum(c["missed_major_parts_equal"] for c in comparisons.values()), len(comparisons)),
        "building_name": agreement(
            sum(c["building_name_equal"] for c in comparisons.values()), len(comparisons)),
        "images": comparisons,
    }
    identities = {}
    for aid, result in judgments.items():
        row, name = selection[aid], result["building_name"]
        expected = sorted(candidates[row["building_id"]]) if row["building_id"] else []
        actual = sorted(names[name]) if name is not None else []
        if name is None:
            status = "unresolved" if row["building_id"] else "no_candidate"
        elif not row["building_id"]:
            status = "no_candidate"
        elif len(expected) == len(actual) == 1:
            status = "not_grouped"
        else:
            status = "match" if expected == actual else "mismatch"
        identities[aid] = {
            "building_name": name, "evidence": list(result["evidence"]),
            "building_id": row["building_id"] or None,
            "building_evidence": row["building_evidence"],
            "title": row["title"], "source_url": row["source_url"],
            "candidate_group": expected, "judged_group": actual,
            "comparison": status,
        }
    identity = {
        "comparison_definition": "同名（非null）のasset集合と既存building_idのasset集合を比較。"
                                 "matchは群構成の一致であり、名称の意味的一致や人手確認ではない。"
                                 "単独同士はnot_grouped、候補あり未同定はunresolved。",
        "assets": identities,
        "groups": [{"building_name": name, "asset_ids": sorted(aids)}
                   for name, aids in sorted(names.items())],
    }
    summary = {
        "images": images, "overall": breakdown(all_regions),
        "labels": {k: breakdown(v) for k, v in sorted(labels.items())},
        "domains": {k: {"images": sum(r["domain"] == k for r in selection.values()),
                         **breakdown(v)} for k, v in sorted(domains.items())},
        "missed_major_parts": dict(sorted(missed.items())), "repeat": repeat_summary,
        "identity": {"named_images": sum(r["building_name"] is not None
                                          for r in judgments.values()),
                     "distinct_names": len(names),
                     "repeated_groups": [g for g in identity["groups"]
                                         if len(g["asset_ids"]) > 1],
                     "candidate_groups": [
                         {"building_id": bid, "asset_ids": sorted(aids),
                          "comparisons": dict(Counter(identities[aid]["comparison"]
                                                      for aid in aids))}
                         for bid, aids in sorted(candidates.items()) if len(aids) > 1],
                     "comparison_counts": dict(Counter(r["comparison"]
                                                       for r in identities.values()))},
    }
    return summary, identity


def prepare(gold, output, resources, taxonomy):
    """selection順に10枚ずつ、全領域を描画する。既存出力への上書きは拒否する。"""
    with (gold / "selection.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    draft = json.loads((gold / "draft.json").read_text(encoding="utf-8"))
    if set(draft["images"]) != {row["filename"] for row in rows}:
        raise ValueError("selectionとdraftの画像が一致しません")
    output.mkdir(parents=True, exist_ok=False)
    parts = yaml.safe_load((taxonomy / "parts.yaml").read_text(encoding="utf-8"))
    terrain = yaml.safe_load((taxonomy / "terrain.yaml").read_text(encoding="utf-8"))
    labels = [label for group in parts["groups"].values() for label in group] + terrain["labels"]
    identity = [{k: row[k] for k in ("asset_id", "title", "source_url", "building_id",
                                    "building_evidence")} for row in rows if row["building_id"]]
    identity_counts = Counter(row["building_id"] for row in identity)
    summaries = []
    font = ImageFont.load_default(size=14)
    for offset in range(0, len(rows), 10):
        batch_id = f"batch-{offset // 10 + 1:02d}"
        directory = output / batch_id
        directory.mkdir()
        for filename in ("judge-prompt.md", "judgment.schema.json"):
            shutil.copyfile(resources / filename, directory / filename)
        _save(directory / "taxonomy-labels.json", labels)
        batch_buildings = {row["building_id"] for row in rows[offset:offset + 10]}
        _save(directory / "identity-candidates.json", [
            row for row in identity
            if row["building_id"] in batch_buildings and identity_counts[row["building_id"]] > 1
        ])
        inputs = {"batch_id": batch_id, "images": []}
        image_tokens = 0
        region_count = 0
        for row in rows[offset:offset + 10]:
            baseline = draft["images"][row["filename"]]
            image = Image.open(gold / "images" / row["filename"]).convert("RGB")
            if image.size != tuple(baseline["annotation_size"]):
                raise ValueError("判定画像が下書きの座標系と一致しません")
            digest = hashlib.sha256((gold / "images" / row["filename"]).read_bytes()).hexdigest()
            panels = [image]
            seen = {}
            regions = []
            for shape in baseline["shapes"]:
                mask = draft_mask(shape["mask"], baseline["annotation_size"])
                key = mask.tobytes()
                if key not in seen:
                    seen[key] = len(panels)
                    pixels = np.asarray(image).copy()
                    pixels[~mask] = (pixels[~mask] * 0.30).astype(np.uint8)
                    pixels[mask] = (pixels[mask] * 0.55 + np.array([255, 40, 40]) * 0.45
                                    ).astype(np.uint8)
                    panels.append(Image.fromarray(pixels))
                raw = shape["mask"]
                left, top, w, h = (int(raw[key]) for key in ("left", "top", "width", "height"))
                regions.append({"draft_id": shape["draft_id"], "label": shape["label"],
                                "area_ratio": shape["area_ratio"],
                                "bbox": [left, top, left + w, top + h],
                                "tile": seen[key]})
            canvas = Image.new("RGB", (1024, math.ceil(len(panels) / 4) * 216), "white")
            draw = ImageDraw.Draw(canvas)
            for index, panel in enumerate(panels):
                panel = panel.copy()
                panel.thumbnail((256, 192), Image.Resampling.LANCZOS)
                x, y = (index % 4) * 256, (index // 4) * 216
                canvas.paste(panel, (x, y + 24))
                draw.text((x + 4, y + 2), "original" if index == 0 else f"tile {index}",
                          font=font, fill="black")
            filename = row["asset_id"] + ".jpg"
            canvas.save(directory / filename, quality=85)
            image_tokens += (85 + 170 * math.ceil(canvas.width / 512)
                             * math.ceil(canvas.height / 512))
            region_count += len(regions)
            inputs["images"].append({
                **{k: row[k] for k in ("asset_id", "title", "source_url", "building_id",
                                      "building_evidence")},
                "image": filename, "image_sha256": digest,
                "annotation_size": baseline["annotation_size"], "regions": regions,
                "sheet_size": list(canvas.size), "tiles": len(panels),
            })
        _save(directory / "input.json", inputs)
        text_bytes = sum(p.stat().st_size for p in directory.glob("*") if p.suffix != ".jpg")
        summaries.append({
            "batch_id": batch_id, "images": len(inputs["images"]), "regions": region_count,
            "image_bytes": sum(p.stat().st_size for p in directory.glob("*.jpg")),
            "text_utf8_bytes": text_bytes, "estimated_image_tokens": image_tokens,
            "estimated_text_tokens": math.ceil(text_bytes / 3),
        })
    _save(output / "summary.json", {
        "batches": summaries,
        "token_estimate": "概算のみ。画像は85+170×512pxタイル数（リサイズ前の保守的算定）。"
                          "テキストはUTF-8 bytes/3。実際のgpt-6.1-solの課金・処理解像度は未計測。",
    })
    _save(output / "repeat-plan.json", {
        "selection": "selection.csvの0始まり行番号が10の倍数（0,10,...,90）。判定前に固定。",
        "images": [row["asset_id"] for row in rows[::10]],
        "execution": "初回の結果を見ず別実行する。フェーズAでは未実行。",
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("prepare")
    create.add_argument("--gold", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--resources", type=Path, default=Path("bench/issue41"))
    create.add_argument("--taxonomy", type=Path, default=Path("taxonomy"))
    validate = sub.add_parser("validate")
    validate.add_argument("--result", type=Path, required=True)
    validate.add_argument("--input", type=Path, required=True)
    validate.add_argument("--schema", type=Path, default=Path("bench/issue41/judgment.schema.json"))
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.gold, args.output, args.resources, args.taxonomy)
    else:
        validate_judgment(*[json.loads(p.read_text(encoding="utf-8")) for p in
                           (args.result, args.input, args.schema)])


if __name__ == "__main__":
    main()
