"""subject内正規化と既知属性による部分層補正。"""

import math
from collections import Counter, defaultdict
from types import SimpleNamespace

from colorstats.collect.coverage import subject_attributes


def asset_attributes(asset):
    """snapshotの確定subject・asset属性を統合し、矛盾の有無とともに返す。

    subjectの地域・年代は既存の収集網羅率と同じ規則で読む。
    assetの実属性を優先し、検索意図は使わない。unknownは既知値を上書きしない。
    """
    data = asset["data"]
    attrs = {}
    if subject := data.get("subject"):
        record = SimpleNamespace(**({
            "domain": asset["domain"], "location": None, "era": None,
        } | subject))
        attrs = {key: value for key, value in subject_attributes(record).items()
                 if value not in (None, "", "unknown")}
    scene = {key: value for key, value in data["scene_attributes"].items()
             if value not in (None, "", "unknown")}
    conflicts = any(key in attrs and attrs[key] != value for key, value in scene.items())
    return attrs | scene | {"domain": asset["domain"]}, conflicts


def compatible_strata(attributes, strata):
    """既知の層属性と矛盾しない層IDを入力順で返す。空配列は対象外。

    domainは必須。そのdomainの目標層が持つ属性だけを照合する。
    欠損・None・空文字・unknownは周辺化し、検索意図や候補から値を補わない。
    conditionsで目標層を先に限定する場合も、この同じ判定を使用する。
    """
    layers = [s for s in strata if s["attributes"]["domain"] == attributes["domain"]]
    keys = {key for s in layers for key in s["attributes"]}
    known = {key: value for key, value in attributes.items()
             if key in keys and value not in (None, "", "unknown")}
    return [s["id"] for s in layers
            if all(s["attributes"].get(key) == value for key, value in known.items())]


def assign_strata(assets, strata):
    """subjectの既知属性辞書（対象外・矛盾ならNone）と除外理由を返す。

    適格画像間の既知値を統合する。unknownは既知値と矛盾せず、複数の両立層も許す。
    各セルでの所属質量はcalculateでqを再正規化して計算する。
    """
    assigned = defaultdict(dict)
    reasons = defaultdict(set)
    for asset in assets.values():
        sid = asset["subject_id"]
        if sid is None or not asset["eligible"]:
            continue
        attrs, conflicts = asset_attributes(asset)
        if conflicts:
            reasons[sid].add("attributes_conflict")
        keys = {key for s in strata if s["attributes"]["domain"] == asset["domain"]
                for key in s["attributes"]}
        attrs = {key: value for key, value in attrs.items() if key in keys}
        if any(key in assigned[sid] and assigned[sid][key] != value
               for key, value in attrs.items()):
            reasons[sid].add("subject_stratum_conflict")
        assigned[sid].update(attrs)
    for sid, attrs in assigned.items():
        if not compatible_strata(attrs, strata):
            reasons[sid].add("outside_target")
    return ({sid: attrs if not reasons[sid] else None for sid, attrs in assigned.items()},
            {sid: sorted(values) for sid, values in reasons.items() if values})


def calculate(rows, strata, conditions, *, cap=None, corrected=True, unknown=False):
    """所属m_shからp_h・r_h・W_s、行重みと実測支持を返す。

    rowsは1条件・役割/pairの点観測。attributesはsubjectの統合済み既知属性で、
    矛盾・対象外はNone。areaは画像内寄与。unknownは未知SHAを別subjectとする感度専用。
    補正率・情報なし割合・属性別未知率の分母は当該セルで採用したsubject数。
    capは感度結果でr_hに適用する上限。主結果では指定しない。
    """
    applicable_ids = set(compatible_strata(conditions, strata))
    applicable = [s for s in strata if s["id"] in applicable_ids]
    target_total = sum(s["subjects"] for s in applicable)
    targets = {s["id"]: s["subjects"] / target_total for s in applicable}
    images = defaultdict(set)
    areas = defaultdict(list)
    attributes = {}
    memberships = {}
    for row in rows:
        sid = row["subject"] or ("unknown:" + row["sha256"] if unknown else None)
        if sid is None:
            continue
        attrs = row["attributes"]
        found = compatible_strata(attrs, applicable) if attrs is not None else []
        if corrected and not found:
            continue
        attributes[sid] = attrs or {}
        total = math.fsum(targets[layer] for layer in found)
        memberships[sid] = {layer: targets[layer] / total for layer in found}
        images[sid].add(row["sha256"])
        areas[sid, row["sha256"]].append(row["area"])
    count = len(attributes)
    probabilities = {
        layer: math.fsum(memberships[sid].get(layer, 0.) for sid in sorted(memberships)) / count
        if count else 0. for layer in targets
    }
    ratios = {layer: targets[layer] / probability
              for layer, probability in probabilities.items() if probability > 0}
    factors = {}
    for sid in sorted(attributes):
        factor = math.fsum(
            mass * (min(ratios[layer], cap) if cap is not None else ratios[layer])
            for layer, mass in memberships[sid].items() if layer in ratios
        ) if corrected else 1.
        factors[sid] = factor
    area_totals = {key: math.fsum(values) for key, values in areas.items()}
    row_weights = []
    for row in rows:
        sid = row["subject"] or ("unknown:" + row["sha256"] if unknown else None)
        row_weights.append(
            factors[sid] / len(images[sid]) * row["area"] / area_totals[sid, row["sha256"]]
            if sid in factors else 0.
        )
    total = math.fsum(factors.values())
    scale = max(factors.values(), default=1.)
    normalized = [w / scale for w in factors.values()]
    square = math.fsum(w * w for w in normalized)
    coverage = math.fsum(q for layer, q in targets.items() if probabilities[layer] > 0)
    keys = sorted({key for s in applicable for key in s["attributes"]} - {"domain"})
    narrowed = sum(0 < len(found) < len(targets) for found in memberships.values())
    no_information = sum(bool(targets) and len(found) == len(targets)
                         for found in memberships.values())
    return row_weights, {
        "sample_count": len({r["sha256"] for r, w in zip(rows, row_weights, strict=True) if w}),
        "subject_count": count, "weight": total,
        "effective_sample_size": math.fsum(normalized) ** 2 / square if square else 0.,
        "max_weight": max(factors.values(), default=0.),
        "max_stratum_weight": max(ratios.values(), default=0.),
        "target_mass_coverage": coverage, "missing_target_mass": 1 - coverage,
        "missing_strata": sorted(set(targets) - ratios.keys()),
        "target_probabilities": targets, "memberships": memberships,
        "stratum_probabilities": probabilities, "stratum_weights": ratios,
        "subject_weights": factors,
        "correction_rate": narrowed / count if count else 0.,
        "no_information_rate": no_information / count if count else 0.,
        "attribute_unknown_rates": {
            key: sum(attrs.get(key) in (None, "", "unknown")
                     for attrs in attributes.values()) / count
            if count else 0. for key in keys
        },
        "unassigned_subjects": len({r["subject"] for r in rows
                                    if r["subject"] and r["subject"] not in factors}),
        "unknown_images": len({r["sha256"] for r in rows if r["subject"] is None}),
        "unassigned_reasons": dict(Counter(
            reason for _, reason in sorted({
                (r["subject"], reason) for r in rows if r["subject"]
                for reason in r.get("unassigned_reasons", [])
            })
        )),
    }
