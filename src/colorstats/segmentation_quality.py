"""統計用分割の固定分割と内部採用判定。公開正解は評価専用。"""

import hashlib
import math

DETAIL = ("band_course", "cornice", "relief")
MAJOR = ("wall", "window", "door", "column")
GATES = {
    "detail_iou_gain": 0.02,
    "detail_precision_gain": 0.02,
    "wall_precision_gain": 0.02,
    "major_iou_loss": 0.01,
    "ade_iou_loss": 0.01,
    "label_precision": 0.50,
}


def split_groups(rows, seed=73):
    """SHAまたは既知subjectで連結した画像群を固定seedで二分する。

    rowsはid・sha256・subject_id（不明はNone）を持つ。未同定subjectの
    独立性は保証しない。入力順によらず同じ群を同じ集合へ割り当てる。
    """
    parents = list(range(len(rows)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    seen = {}
    for index, row in enumerate(rows):
        for field in ("sha256", "subject_id"):
            if row[field] is None:
                continue
            key = (field, row[field])
            if key in seen:
                parents[root(index)] = root(seen[key])
            seen[key] = index
    groups = {}
    for index, row in enumerate(rows):
        groups.setdefault(root(index), []).append(row["id"])
    result = {}
    for members in groups.values():
        group = min(members)
        digest = hashlib.sha256(f"{seed}:{group}".encode()).hexdigest()
        split = "holdout" if int(digest[:8], 16) % 2 else "tune"
        result.update({member: {"group": group, "split": split} for member in members})
    return result


def indicators(reports):
    """対応グループのマクロ平均。分母0があれば採用指標はNone。"""
    def mean(dataset, labels, metric):
        values = [reports[dataset][label][metric] for label in labels]
        return sum(values) / len(values) if all(v is not None for v in values) else None

    return {
        "detail_iou": mean("cmp", DETAIL, "iou"),
        "detail_precision": mean("cmp", DETAIL, "precision"),
        "wall_precision": reports["cmp"]["wall"]["precision"],
        "major_iou": mean("cmp", MAJOR, "iou"),
        "ade_iou": mean("ade", reports["ade"], "iou"),
    }


def adoption(baseline, candidate):
    """同一holdoutの指標を比較。欠測・閾値未達なら既定設定を維持する。"""
    before, after = indicators(baseline), indicators(candidate)
    limits = {
        "detail_iou": GATES["detail_iou_gain"],
        "detail_precision": GATES["detail_precision_gain"],
        "wall_precision": GATES["wall_precision_gain"],
        "major_iou": -GATES["major_iou_loss"],
        "ade_iou": -GATES["ade_iou_loss"],
    }
    deltas = {
        key: after[key] - before[key]
        if before[key] is not None and after[key] is not None else None
        for key in limits
    }
    checks = {
        key: value is not None and (
            value >= limits[key] or math.isclose(value, limits[key], rel_tol=0, abs_tol=1e-12)
        )
        for key, value in deltas.items()
    }
    return {"accepted": all(checks.values()), "checks": checks, "deltas": deltas}


def label_support(reports, mapping, labels):
    """ラベルごとの対応範囲と支持状態。複数対応は全データのprecision通過が必要。

    複数taxonomyラベルの和集合しか正解対応できない場合、個別ラベルは
    validatedにしない。group_onlyとして診断に残す。
    """
    result = {}
    for label in sorted(labels):
        evidence = []
        for dataset, definition in mapping["datasets"].items():
            for group, value in definition["groups"].items():
                if label in value["labels"]:
                    evidence.append({
                        "dataset": dataset, "group": group,
                        "labels": value["labels"], **reports[dataset][group],
                    })
        supported = bool(evidence) and all(
            row["labels"] == [label]
            and row["precision"] is not None
            and row["precision"] >= GATES["label_precision"]
            and row["tp"] > 0 for row in evidence
        )
        result[label] = {
            "status": "validated" if supported else (
                "unmapped" if not evidence else
                "group_only" if any(len(row["labels"]) > 1 for row in evidence) else "below_gate"
            ),
            "supported": supported, "evidence": evidence,
        }
    return result


def group_support(reports, mapping, roles):
    """明示した和集合と完全一致する正解群だけで粗い役割の支持を返す。

    rolesは役割名から構成ラベルへの対応。子ラベルや部分集合の支持は保証しない。
    同一役割が複数データに対応する場合は全対応のゲート通過を必要とする。
    """
    grouped = {"datasets": {}}
    for dataset, definition in mapping["datasets"].items():
        groups = {}
        for name, value in definition["groups"].items():
            matched = [role for role, members in roles.items()
                       if set(value["labels"]) == set(members)]
            if matched:
                groups[name] = {**value, "labels": matched}
        grouped["datasets"][dataset] = {"groups": groups}
    result = label_support(reports, grouped, roles)
    for role, row in result.items():
        row["members"] = roles[role]
    return result
