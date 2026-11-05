"""固定reportの支持不足を収集元が参照できる原因別一覧へ変換する。"""

import argparse
import json
from collections import Counter
from pathlib import Path

import duckdb

from colorstats.stats.aggregate import _points, _read
from colorstats.stats.aggregate_cli import load_settings
from colorstats.stats.snapshot import canonical
from colorstats.stats.snapshot import verify as verify_snapshot
from colorstats.stats.weights import asset_attributes, assign_strata, calculate, compatible_strata


def deficits(report, *, snapshot=None, settings=None):
    """#76 reportから部位・relation・層の不足を返す。原因は重複を許す。

    10 subjectと直接分布30 subject・n_effの不足を別々に示す。
    和集合未保存・モデル未検証は収集枚数だけで解消できる不足に数えない。
    """
    rows = []
    for row in report["support"]:
        quality = row["quality"]
        causes = []
        if any(rate > 0 for rate in row["attribute_unknown_rates"].values()):
            causes.append("属性不足")
        if min(row["subject_count"], row["effective_sample_size"]) < 30:
            causes.append("subject不足")
        if "model_unvalidated" in quality["flags"]:
            causes.append("部位不足")
        rows.append({
            "scope": "condition", "conditions": row["conditions"],
            "parts": row["target_parts"], "kind": row["kind"],
            "subject_count": row["subject_count"],
            "effective_sample_size": row["effective_sample_size"],
            "subject_deficit_10": max(0, 10 - row["subject_count"]),
            "subject_deficit_30": max(0, 30 - row["subject_count"]),
            "n_eff_deficit_10": max(0, 10 - row["effective_sample_size"]),
            "n_eff_deficit_30": max(0, 30 - row["effective_sample_size"]),
            "attribute_unknown_rates": row["attribute_unknown_rates"], "causes": causes,
        })
    for row in report["rights_support"]:
        if row["scope"] != "stratum":
            continue
        causes = []
        if row["adopted_subjects"] < 30:
            causes.append("subject不足")
        if (not row["model_validated"] or not row["complete"]
                or row["subjects_after_analysis"] > row["adopted_subjects"]):
            causes.append("部位不足")
        if row["lost_subjects_d15"]:
            causes.append("権利除外")
        layer = next(s for s in report["strata"] if s["id"] == row["stratum"])
        if layer["intent_comparison"]["attributes_missing"]["numerator"]:
            causes.append("属性不足")
        rows.append({
            "scope": "stratum", "stratum": row["stratum"],
            "conditions": row["conditions"], "parts": [row["role"]], "kind": row["kind"],
            "subject_count": row["adopted_subjects"],
            "subject_deficit_10": max(0, 10 - row["adopted_subjects"]),
            "subject_deficit_30": max(0, 30 - row["adopted_subjects"]),
            "lost_subjects_d15": row["lost_subjects_d15"],
            "model_validated": row["model_validated"],
            "unverified_union_assets": row["unverified_union_assets"], "causes": causes,
        })
    if snapshot is not None:
        rows += layer_relations(snapshot, report, settings)
    return {"snapshot_id": report["snapshot_id"], "thresholds": {"role": 10, "direct": 30},
            "cause_counts_overlapping": dict(Counter(c for row in rows for c in row["causes"])),
            "rows": rows,
            "strata": [{"id": s["id"], "subject_deficit": s["inferred"]["subject_deficit"],
                        "attribute_missing_images": s["intent_comparison"]["attributes_missing"]}
                       for s in report["strata"]]}


def layer_relations(snapshot, report, settings):
    """既存集計の点観測・重みで各目標層のrelation支持を測る。未観測pairも0で残す。"""
    manifest = verify_snapshot(snapshot, report["snapshot_id"])
    with duckdb.connect() as db:
        for table in ("assets", "regions", "observations", "groups", "relations"):
            db.read_parquet(str(Path(snapshot) / (table + ".parquet"))).create_view(table)
        assets = {r["id"]: r for r in _read(db, "assets")}
        assigned, reasons = assign_strata(assets, settings["strata"])
        points = []
        for aid, kind, parts, area, _metrics in _points(db, assets, manifest["quality"]):
            if kind != "relation":
                continue
            asset = assets[aid]
            points.append((aid, tuple(sorted(parts)), {
                "subject": asset["subject_id"], "sha256": asset["sha256"], "area": area,
                "attributes": assigned.get(asset["subject_id"]),
                "unassigned_reasons": reasons.get(asset["subject_id"], []),
            }))
    rows = []
    for layer in settings["strata"]:
        domain = layer["attributes"]["domain"]
        templates = {tuple(sorted(r["target_parts"])) for r in report["support"]
                     if r["kind"] == "relation" and r["conditions"]["domain"] == domain}
        selected = {aid for aid, asset in assets.items() if layer["id"] in compatible_strata(
            asset_attributes(asset)[0], settings["strata"])}
        for parts in sorted(templates):
            observations = [row for aid, pair, row in points if aid in selected and pair == parts]
            _, quality = calculate(observations, settings["strata"], layer["attributes"])
            count, effective = quality["subject_count"], quality["effective_sample_size"]
            supported = (set(manifest["quality"]["supported_by_domain"].get(domain, []))
                         | {key.split("/", 1)[1] for key in
                            manifest["quality"].get("group_members", {})
                            if key.startswith(domain + "/")})
            causes = ["subject不足"] if min(count, effective) < 30 else []
            if not set(parts) <= supported:
                causes.append("部位不足")
            if any(v > 0 for v in quality["attribute_unknown_rates"].values()):
                causes.append("属性不足")
            rows.append({"scope": "stratum", "stratum": layer["id"], "kind": "relation",
                         "conditions": layer["attributes"], "parts": list(parts),
                         "subject_count": count, "effective_sample_size": effective,
                         "subject_deficit_10": max(0, 10 - count),
                         "subject_deficit_30": max(0, 30 - count),
                         "n_eff_deficit_10": max(0, 10 - effective),
                         "n_eff_deficit_30": max(0, 30 - effective), "causes": causes})
    return rows


def main():
    parser = argparse.ArgumentParser(description="固定reportから原因別の支持不足を出力する")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--config", type=Path, default=Path("configs/stats.yaml"))
    parser.add_argument("--targets", type=Path, default=Path("configs/collection_targets.yaml"))
    parser.add_argument("--taxonomy", type=Path, default=Path("taxonomy"))
    args = parser.parse_args()
    settings = load_settings(args.config, args.targets, args.taxonomy) if args.snapshot else None
    result = deficits(json.loads(args.report.read_text(encoding="utf-8")),
                      snapshot=args.snapshot, settings=settings)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(canonical(result) + "\n")
    print(canonical({k: v for k, v in result.items() if k not in {"rows", "strata"}}))


if __name__ == "__main__":
    main()
