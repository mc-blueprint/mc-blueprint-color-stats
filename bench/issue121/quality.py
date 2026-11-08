"""#121の全非void画素評価と、未確認を合格にしない品質判定。"""

from collections import Counter

import numpy as np

from colorstats.segmentation_evaluation import pixel_counts, scores


def measure(truth, predictions, groups, *, max_id):
    """正解0だけをvoidとし、対応外クラスも負例に含める。

    同じ群の予測は和集合。混同行列は群ごとの二値TP/FP/FN/TNと、
    予測上の全正解IDヒストグラムを返す。異群間重複は消さない。
    """
    if truth.ndim != 2 or not np.isin(truth, range(max_id + 1)).all():
        raise ValueError("正解IDがデータセットの範囲外です")
    counts = pixel_counts(truth, predictions, groups, valid_ids=range(1, max_id + 1))
    merged = {key: np.zeros(truth.shape, dtype=bool) for key in groups}
    all_masks = np.zeros(truth.shape, dtype=bool)
    for label, mask in predictions:
        if mask.shape != truth.shape or mask.dtype != np.bool_:
            raise ValueError("予測maskは正解と同寸のbool配列が必要です")
        all_masks |= mask
        for key, group in groups.items():
            if label in group["labels"]:
                merged[key] |= mask
    valid = truth != 0
    for key, mask in merged.items():
        value = counts[key]
        value["tn"] = int(valid.sum()) - value["tp"] - value["fp"] - value["fn"]
        value["truth_histogram"] = np.bincount(truth[mask], minlength=max_id + 1).tolist()
    overlaps = np.zeros(truth.shape, dtype=np.uint16)
    for mask in merged.values():
        overlaps += mask
    mapped_ids = [i for group in groups.values() for i in group["ids"]]
    return {"groups": counts, "coverage": {
        "images": 1, "pixels": truth.size, "nonvoid_pixels": int(valid.sum()),
        "truth_void_pixels": int((~valid).sum()),
        "unmapped_nonvoid_pixels": int((valid & ~np.isin(truth, mapped_ids)).sum()),
        "predicted_nonvoid_pixels": int((all_masks & valid).sum()),
        "prediction_void_pixels": int((~all_masks & valid).sum()),
        "predicted_on_truth_void_pixels": int((all_masks & ~valid).sum()),
        "group_overlap_pixels": int(((overlaps > 1) & valid).sum()),
    }}


def aggregate(results):
    """画像ごとの整数計数を加算し、画素数を分母に指標を算出する。"""
    coverage, groups = Counter(), {}
    for result in results:
        coverage.update(result["coverage"])
        for name, values in result["groups"].items():
            item = groups.setdefault(name, {"tp": 0, "fp": 0, "fn": 0, "tn": 0,
                                            "truth_histogram": [0] * len(values[
                                                "truth_histogram"])})
            for key in ("tp", "fp", "fn", "tn"):
                item[key] += values[key]
            item["truth_histogram"] = [a + b for a, b in zip(
                item["truth_histogram"], values["truth_histogram"], strict=True)]
    denominator = coverage["nonvoid_pixels"]
    return {"groups": {name: scores(value) for name, value in groups.items()},
            "coverage": {**coverage, "coverage": coverage["predicted_nonvoid_pixels"]
                         / denominator if denominator else None,
                         "void_rate": coverage["prediction_void_pixels"]
                         / denominator if denominator else None}}


def part_decision(metrics):
    """固定のprecision>=0.80、recall>=0.30を全群へ適用する。空予測は不合格。"""
    result = {}
    for name, value in metrics.items():
        observed = value["tp"] + value["fn"] > 0
        passed = (value["tp"] > 0 and (value["precision"] or 0) >= 0.80
                  and (value["recall"] or 0) >= 0.30)
        result[name] = {"status": "unverified" if not observed else (
            "passed" if passed else "failed"), "precision": value["precision"],
            "recall": value["recall"], "iou": value["iou"],
            "reason": "正例画素なし" if not observed else "全非void画素の直接計数",
            "supported": bool(observed and passed)}
    return result


def person_decision(*, selected, reviewed, accepted, missed):
    """採用分の全件確認と0見落としを要求し、片側95%上限を採用分母で返す。"""
    complete = selected >= 50 and reviewed == selected and accepted > 0
    status = "failed" if missed else "passed" if complete else "unverified"
    return {"status": status, "selected": selected, "reviewed": reviewed,
            "accepted": accepted, "missed": missed,
            "zero_miss_upper_95": 1 - 0.05 ** (1 / accepted)
            if complete and missed == 0 else None,
            "limitation": "約100枚で0件でも、見落とし率は約3%を超えないまで。"
            "各cohort・採用分の分母が小さければ上限はさらに大きい。"}
