"""重み付き経験分布と円周ヒストグラム。"""

import math
from collections import defaultdict

QUANTILES = (.05, .25, .50, .75, .95)


def empirical(values):
    """(値, 正の重み)から同値をまとめた確率質量を値順で返す。"""
    grouped = defaultdict(list)
    for value, weight in values:
        if not math.isfinite(value) or not math.isfinite(weight) or weight <= 0:
            raise ValueError("有限な値と正の重みが必要です")
        grouped[value].append(weight)
    masses = [(value, math.fsum(sorted(weights))) for value, weights in sorted(grouped.items())]
    total = math.fsum(weight for _, weight in masses)
    return [[value, weight / total] for value, weight in masses]


def quantiles(masses):
    """累積質量がq以上となる最小値を返す。空分布は空配列。"""
    if not masses:
        return []
    result = []
    for q in QUANTILES:
        value = masses[-1][0]
        cumulative = 0.
        for candidate, mass in masses:
            cumulative = math.fsum((cumulative, mass))
            if cumulative >= q:
                value = candidate
                break
        result.append({"q": q, "value": value})
    return result


def summarize(rows, weights, kind):
    """行のmetricsと対応する重みを、軸別経験CDF・分位点へ変換する。"""
    axes = ("L", "a", "b") if kind == "palette" else (
        "delta_l", "delta_c", "delta_e_ok", "area_ratio",
    )
    result = {"cdf": {}, "quantiles": {}}
    for axis in axes:
        masses = empirical((row["metrics"][axis], weight)
                           for row, weight in zip(rows, weights, strict=True) if weight > 0)
        result["cdf"][axis] = masses
        result["quantiles"][axis] = quantiles(masses)
    if kind == "relation":
        bins = [[] for _ in range(36)]
        nulls = []
        for row, weight in zip(rows, weights, strict=True):
            hue = row["metrics"]["delta_h"]
            if hue is None:
                nulls.append(weight)
            else:
                bins[int(((hue + 180) % 360) // 10)].append(weight)
        total = math.fsum(weights)
        result["hue"] = {
            "range": [-180, 180],
            "bins": [math.fsum(v) / total for v in bins] if total else [0.] * 36,
            "null_mass": math.fsum(nulls) / total if total else 0.,
        }
    return result


def mix(child, parent, coefficient):
    """分位点ではなく経験CDFと円周確率質量を混合する。入力は変更しない。"""
    result = {"cdf": {}, "quantiles": {}}
    for axis in parent["cdf"]:
        masses = empirical(
            [(v, w * coefficient) for v, w in child["cdf"][axis] if w * coefficient > 0]
            + [(v, w * (1 - coefficient)) for v, w in parent["cdf"][axis]
               if w * (1 - coefficient) > 0]
        )
        result["cdf"][axis] = masses
        result["quantiles"][axis] = quantiles(masses)
    if "hue" in parent:
        result["hue"] = {
            "range": [-180, 180],
            "bins": [coefficient * a + (1 - coefficient) * b
                     for a, b in zip(child["hue"]["bins"], parent["hue"]["bins"], strict=True)],
            "null_mass": coefficient * child["hue"]["null_mass"]
                         + (1 - coefficient) * parent["hue"]["null_mass"],
        }
    return result
