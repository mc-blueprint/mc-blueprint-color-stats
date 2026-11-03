"""subject内正規化と目標層への事後層化。"""

import math
from collections import Counter, defaultdict
from types import SimpleNamespace

from colorstats.collect.coverage import subject_attributes


def asset_attributes(asset):
    """snapshotの確定subject・asset属性を統合し、矛盾の有無とともに返す。

    subjectの地域・年代は既存の収集網羅率と同じ規則で読む。
    assetの実属性を優先し、検索意図は使わない。
    """
    data = asset["data"]
    attrs = {}
    if subject := data.get("subject"):
        record = SimpleNamespace(**({
            "domain": asset["domain"], "location": None, "era": None,
        } | subject))
        attrs = {key: value for key, value in subject_attributes(record).items()
                 if value is not None}
    scene = data["scene_attributes"]
    conflicts = any(key in attrs and attrs[key] != value for key, value in scene.items())
    return attrs | scene | {"domain": asset["domain"]}, conflicts


def assign_strata(assets, strata):
    """確定subjectの一意な目標層と未割当理由を返す。検索意図は使わない。"""
    assignments = defaultdict(set)
    reasons = defaultdict(set)
    for asset in assets.values():
        sid = asset["subject_id"]
        if sid is None or not asset["eligible"]:
            continue
        attrs, conflicts = asset_attributes(asset)
        found = [s["id"] for s in strata
                 if all(attrs.get(k) == v for k, v in s["attributes"].items())]
        assignments[sid].add(found[0] if len(found) == 1 and not conflicts else None)
        if conflicts:
            reasons[sid].add("attributes_conflict")
        elif len(found) > 1:
            reasons[sid].add("multiple_strata")
        elif not found:
            domain_layers = [s for s in strata if s["attributes"]["domain"] == asset["domain"]]
            missing = any(set(s["attributes"]) - attrs.keys() for s in domain_layers)
            reasons[sid].add("attributes_missing" if missing else "outside_target")
    assigned = {}
    for sid, found in assignments.items():
        assigned[sid] = next(iter(found)) if len(found) == 1 else None
        if len(found) > 1:
            reasons[sid].add("subject_stratum_conflict")
    return assigned, {sid: sorted(values) for sid, values in reasons.items()}


def calculate(rows, strata, conditions, *, cap=None, corrected=True, unknown=False):
    """行重みと実測支持を返す。層0件は目標質量欠損として残す。

    rowsは1条件・役割/pairの点観測。areaは画像内寄与、stratumは
    subject全体で一意に確定した層。unknownは未知SHAを別subjectとする感度専用。
    """
    applicable = [s for s in strata if all(
        conditions.get(k, v) == v for k, v in s["attributes"].items()
    )]
    total_target = sum(s["subjects"] for s in applicable)
    targets = {s["id"]: s["subjects"] / total_target for s in applicable}
    images = defaultdict(set)
    areas = defaultdict(list)
    subjects = {}
    for row in rows:
        sid = row["subject"] or ("unknown:" + row["sha256"] if unknown else None)
        if sid is None or (corrected and row["stratum"] not in targets):
            continue
        subjects[sid] = row["stratum"]
        images[sid].add(row["sha256"])
        areas[sid, row["sha256"]].append(row["area"])
    counts = Counter(subjects.values())
    factors = {}
    for sid, layer in sorted(subjects.items()):
        factor = targets[layer] * len(subjects) / counts[layer] if corrected else 1.
        factors[sid] = min(factor, cap) if cap is not None else factor
    weights = []
    for row in rows:
        sid = row["subject"] or ("unknown:" + row["sha256"] if unknown else None)
        weight = 0.
        if sid in factors:
            weight = (factors[sid] / len(images[sid]) * row["area"]
                      / math.fsum(areas[sid, row["sha256"]]))
        weights.append(weight)
    total = math.fsum(factors.values())
    scale = max(factors.values(), default=1.)
    normalized = [w / scale for w in factors.values()]
    square = math.fsum(w * w for w in normalized)
    coverage = math.fsum(q for layer, q in targets.items() if counts[layer])
    return weights, {
        "sample_count": len({r["sha256"] for r, w in zip(rows, weights, strict=True) if w}),
        "subject_count": len(subjects), "weight": total,
        "effective_sample_size": math.fsum(normalized) ** 2 / square if square else 0.,
        "max_weight": max(factors.values(), default=0.),
        "target_mass_coverage": coverage, "missing_target_mass": 1 - coverage,
        "missing_strata": sorted(set(targets) - counts.keys()),
        "unassigned_subjects": len({r["subject"] for r in rows
                                    if r["subject"] and r["stratum"] not in targets}),
        "unknown_images": len({r["sha256"] for r in rows if r["subject"] is None}),
        "unassigned_reasons": {
            reason: len({r["subject"] for r in rows
                         if r["subject"] and reason in r.get("unassigned_reasons", [])})
            for reason in sorted({reason for r in rows
                                  for reason in r.get("unassigned_reasons", [])})
        },
    }
