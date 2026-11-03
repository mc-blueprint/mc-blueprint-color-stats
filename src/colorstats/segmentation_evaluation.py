"""公開ラベルマップに合わせた、DBを使わない画素単位の分割評価。"""

import numpy as np


def pixel_counts(truth, predictions, groups, *, valid_ids=None):
    """グループごとのTP/FP/FNを返す（同寸のID正解とbool予測）。

    対応のない正解IDの画素は無視する。同一グループの候補は和集合にし、
    異なるグループへの重複予測は残して誤ラベル側のFPとして数える。
    predictionsは(label, mask)の列で、未検出ラベルは空マスクとして扱う。
    valid_idsを指定すると、対応群を外しても評価画素集合を固定できる。
    """
    if valid_ids is None:
        valid_ids = [i for group in groups.values() for i in group["ids"]]
    valid = np.isin(truth, valid_ids)
    merged = {name: np.zeros(truth.shape, dtype=bool) for name in groups}
    for label, mask in predictions:
        if mask.shape != truth.shape or mask.dtype != np.bool_:
            raise ValueError("予測マスクは正解と同寸のbool配列が必要です")
        for name, group in groups.items():
            if label in group["labels"]:
                merged[name] |= mask
    result = {}
    for name, group in groups.items():
        expected = np.isin(truth, group["ids"])
        predicted = merged[name] & valid
        result[name] = {
            "tp": int(np.count_nonzero(predicted & expected)),
            "fp": int(np.count_nonzero(predicted & ~expected)),
            "fn": int(np.count_nonzero(~predicted & expected)),
        }
    return result


def scores(counts):
    """集積した画素数からIoU・適合率・再現率を返す。分母0はNone。"""
    tp, fp, fn = (counts[key] for key in ("tp", "fp", "fn"))
    return {**counts, **{
        key: tp / denominator if denominator else None
        for key, denominator in (
            ("iou", tp + fp + fn), ("precision", tp + fp), ("recall", tp + fn)
        )
    }}


def select_ade(truth, rule):
    """屋外の代理条件と対象面積率を満たすか返す。条件はYAMLを正本とする。"""
    sky = np.mean(truth == rule["sky_id"])
    outdoor = np.mean(np.isin(truth, rule["outdoor_ids"]))
    indoor = np.mean(np.isin(truth, rule["indoor_ids"]))
    subject = np.mean(np.isin(truth, rule["subject_ids"]))
    return bool(
        (sky >= rule["min_sky_ratio"] or outdoor >= rule["min_outdoor_ratio_without_sky"])
        and indoor <= rule["max_indoor_ratio"] and subject >= rule["min_subject_ratio"]
    )
