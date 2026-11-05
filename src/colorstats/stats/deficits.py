"""taxonomyの全役割・全pairについて、未観測を含む支持不足を出力する。"""

import argparse
import json
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import duckdb

from colorstats.schema.taxonomy import load_taxonomy
from colorstats.stats.aggregate import _points, _read
from colorstats.stats.aggregate_cli import load_settings
from colorstats.stats.snapshot import canonical
from colorstats.stats.snapshot import verify as verify_snapshot
from colorstats.stats.weights import asset_attributes, assign_strata, calculate, compatible_strata


def deficits(report, *, snapshot=None, settings=None, taxonomy=Path("taxonomy")):
    """固定reportとtaxonomyから全条件・目標層のpaletteと無向pairを列挙する。

    snapshot指定時は同じsettingsが必須で、層別支持を既存の点観測・重みで計算する。
    未指定時の層別n_effはNoneとし、未計測を0件の実測と混同しない。
    10/30 subject・n_effの不足と重複を許す原因分類を返す。元データは更新しない。
    taxonomy不一致・snapshot不一致・I/Oエラーは呼出し元へ返す。
    """
    documents = load_taxonomy(taxonomy)
    if documents["parts"]["taxonomy_version"] != report["taxonomy_version"]:
        raise ValueError("taxonomy版がreportと一致しません")
    groups = documents["parts"]["groups"]
    roles = {"real_building": sorted({*groups, *(p for parts in groups.values() for p in parts)}),
             "real_terrain": sorted({"tree", *documents["terrain"]["labels"]})}
    layers = {s["id"]: s for s in report["strata"]}
    condition_rows = {(canonical(r["conditions"]), r["kind"], tuple(sorted(r["target_parts"]))): r
                      for r in report["support"]}
    conditions = {canonical(r["conditions"]): r["conditions"] for r in report["support"]}
    conditions.update({canonical({"domain": d}): {"domain": d} for d in roles})
    rights = {(r["scope"], r["stratum"], canonical(r["conditions"]), r["role"]): r
              for r in report["rights_support"]}
    measurements = layer_support(snapshot, report, settings) if snapshot is not None else {}
    scopes = [("condition", None, conditions[key]) for key in sorted(conditions)]
    scopes += [("stratum", key, s["attributes"]) for key, s in layers.items()]
    rows = []
    for scope, stratum, condition in scopes:
        domain = condition["domain"]
        supported = (set(report["model_quality"]["supported_by_domain"].get(domain, []))
                     | {key.split("/", 1)[1] for key in
                        report["model_quality"].get("group_members", {})
                        if key.startswith(domain + "/")})
        templates = [("palette", (p,)) for p in roles[domain]]
        templates += [("relation", pair) for pair in combinations(roles[domain], 2)]
        for kind, parts in templates:
            source = condition_rows.get((canonical(condition), kind, parts), {})
            recorded = rights.get((scope, stratum, canonical(condition), parts[0]), {}) \
                if kind == "palette" else {}
            if scope == "condition":
                count = source.get("subject_count", 0)
                effective = source.get("effective_sample_size", 0.)
                unknown = source.get("attribute_unknown_rates", {})
            elif snapshot is not None:
                quality = measurements.get((stratum, kind, parts), {})
                count = quality.get("subject_count", 0)
                effective = quality.get("effective_sample_size", 0.)
                unknown = quality.get("attribute_unknown_rates", {})
            else:
                count, effective, unknown = recorded.get("adopted_subjects", 0), None, {}
            validated = set(parts) <= supported
            causes = []
            if count < 30 or effective is not None and effective < 30:
                causes.append("subject不足")
            if not validated or not recorded.get("complete", True):
                causes.append("部位不足")
            if recorded.get("lost_subjects_d15"):
                causes.append("権利除外")
            if (any(rate > 0 for rate in unknown.values()) or stratum is not None
                    and layers[stratum]["intent_comparison"]["attributes_missing"]["numerator"]):
                causes.append("属性不足")
            rows.append({
                "scope": scope, "stratum": stratum, "conditions": condition,
                "parts": list(parts), "kind": kind, "subject_count": count,
                "effective_sample_size": effective, "model_validated": validated,
                "subject_deficit_10": max(0, 10 - count),
                "subject_deficit_30": max(0, 30 - count),
                "n_eff_deficit_10": max(0, 10 - effective) if effective is not None else None,
                "n_eff_deficit_30": max(0, 30 - effective) if effective is not None else None,
                "attribute_unknown_rates": unknown,
                "lost_subjects_d15": recorded.get("lost_subjects_d15"), "causes": causes,
            })
    counts = Counter(c for row in rows for c in row["causes"])
    return {"snapshot_id": report["snapshot_id"], "taxonomy_version": report["taxonomy_version"],
            "thresholds": {"role": 10, "direct": 30},
            "cause_counts_overlapping": {c: counts[c] for c in
                                         ("属性不足", "subject不足", "部位不足", "権利除外")},
            "domain_role_counts": {d: len(parts) for d, parts in roles.items()},
            "terrain_relation_rows": sum(r["kind"] == "relation"
                                         and r["conditions"]["domain"] == "real_terrain"
                                         for r in rows),
            "rows": rows,
            "strata": [{"id": s["id"], "subject_deficit": s["inferred"]["subject_deficit"],
                        "attribute_missing_images": s["intent_comparison"]["attributes_missing"]}
                       for s in layers.values()]}


def layer_support(snapshot, report, settings):
    """保存済みの適格点観測を層・kind・pairでまとめて既存の重み計算へ渡す。"""
    manifest = verify_snapshot(snapshot, report["snapshot_id"])
    with duckdb.connect() as db:
        for table in ("assets", "regions", "observations", "groups", "relations"):
            db.read_parquet(str(Path(snapshot) / (table + ".parquet"))).create_view(table)
        assets = {r["id"]: r for r in _read(db, "assets")}
        assigned, reasons = assign_strata(assets, settings["strata"])
        memberships = {aid: compatible_strata(asset_attributes(asset)[0], settings["strata"])
                       for aid, asset in assets.items()}
        cells = defaultdict(list)
        for aid, kind, parts, area, _ in _points(db, assets, manifest["quality"]):
            asset = assets[aid]
            for layer in memberships[aid]:
                cells[layer, kind, tuple(sorted(parts))].append({
                    "subject": asset["subject_id"], "sha256": asset["sha256"], "area": area,
                    "attributes": assigned.get(asset["subject_id"]),
                    "unassigned_reasons": reasons.get(asset["subject_id"], []),
                })
    attributes = {s["id"]: s["attributes"] for s in settings["strata"]}
    return {key: calculate(rows, settings["strata"], attributes[key[0]])[1]
            for key, rows in cells.items()}


def main():
    parser = argparse.ArgumentParser(description="taxonomy全役割・pairの原因別支持不足")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--config", type=Path, default=Path("configs/stats.yaml"))
    parser.add_argument("--targets", type=Path, default=Path("configs/collection_targets.yaml"))
    parser.add_argument("--taxonomy", type=Path, default=Path("taxonomy"))
    args = parser.parse_args()
    settings = load_settings(args.config, args.targets, args.taxonomy) if args.snapshot else None
    result = deficits(json.loads(args.report.read_text(encoding="utf-8")), snapshot=args.snapshot,
                      settings=settings, taxonomy=args.taxonomy)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(canonical(result) + "\n")
    print(canonical({k: v for k, v in result.items() if k not in {"rows", "strata"}}))


if __name__ == "__main__":
    main()
