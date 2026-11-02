"""同一建築・同一部位の材質色を対応のある画像対で比較する。"""

import argparse
import json
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

from colorstats.analyze.shade import METHODS


def compare(samples: list[dict]) -> dict:
    """画像・部位ごとの材質色を受け、手法共通の画像対のΔE_okを集計する。

    必須キーはsubject_id/asset_id/sha256/label_source/label/method/material_oklab。
    material_oklabは3成分。各キーは一意、同一SHAの別assetは拒否する。
    同じ意味ラベルの複数instanceは呼出し側で有効画素数による加重平均にする。
    modelとhumanを混ぜず、共通する画像対だけを同じ母数で評価する。
    画像数の多い建築が支配しないよう部位内、建築内、建築間の順に平均する。
    """
    cells = defaultdict(lambda: defaultdict(dict))
    hashes = {}
    for row in samples:
        if row["method"] not in METHODS or row["label_source"] not in {"model", "human"}:
            raise ValueError("未知の手法またはマスク由来です")
        asset = row["asset_id"]
        owner = hashes.setdefault(row["sha256"], asset)
        if owner != asset:
            raise ValueError("同じ原本の重複assetを評価できません")
        key = (row["label_source"], row["subject_id"], row["label"])
        values = cells[key][row["method"]]
        if asset in values:
            raise ValueError("同じ画像・部位・手法の観測が重複しています")
        vector = np.asarray(row["material_oklab"], dtype=float)
        if vector.shape != (3,) or not np.isfinite(vector).all():
            raise ValueError("材質色は有限なOKLab 3成分です")
        values[asset] = vector
    results = {source: {"cells": [], "methods": {}, "subjects": 0, "pairs": 0}
               for source in ("model", "human")}
    for (source, subject, label), methods in sorted(cells.items()):
        common = sorted(set.intersection(*(set(methods[method]) for method in METHODS)))
        pairs = list(combinations(common, 2))
        if not pairs:
            continue
        means = {method: float(np.mean([
            np.linalg.norm(methods[method][a] - methods[method][b]) for a, b in pairs
        ])) for method in METHODS}
        results[source]["cells"].append({
            "subject_id": subject, "label": label, "assets": common,
            "pairs": len(pairs), "mean_delta_e_ok": means,
        })
    for result in results.values():
        subjects = sorted({cell["subject_id"] for cell in result["cells"]})
        result["subjects"] = len(subjects)
        result["pairs"] = sum(cell["pairs"] for cell in result["cells"])
        for method in METHODS:
            by_subject = {subject: float(np.mean([
                cell["mean_delta_e_ok"][method] for cell in result["cells"]
                if cell["subject_id"] == subject
            ])) for subject in subjects}
            result["methods"][method] = {
                "mean_delta_e_ok": float(np.mean(list(by_subject.values())))
                if subjects else None,
                "by_subject": by_subject,
            }
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("samples", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = compare(json.loads(args.samples.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
                           + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
