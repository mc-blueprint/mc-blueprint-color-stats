"""固定snapshotの条件分布生成とQueue完了取引での登録。"""

import json
import math
import uuid
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import duckdb
from sqlalchemy import null, select

from colorstats.queue.core import RunInfo
from colorstats.queue.worker import Prepared
from colorstats.schema.models import ProcessingRun, ProcessingRunInput, RuleStat
from colorstats.stats import distributions, weights
from colorstats.stats.snapshot import canonical, digest, verify

CODE_VERSION = "aggregate-v2"


def config_hash(payload):
    """パスに依存せずsnapshot・固定設定・実装版を集計キーへ含める。"""
    return digest({k: v for k, v in payload.items() if k not in {"snapshot", "output_path"}}
                  | {"implementation": CODE_VERSION})


def _read(db, table, *, eligible=False):
    condition = " WHERE eligible" if eligible else ""
    cursor = db.execute(f"SELECT * FROM {table}{condition} ORDER BY ALL")
    columns = [column[0] for column in cursor.description]
    while batch := cursor.fetchmany(256):
        for values in batch:
            row = dict(zip(columns, values, strict=True))
            for key in ("data", "reasons"):
                if key in row:
                    row[key] = json.loads(row[key])
            yield row


def _conditions(attrs):
    domain = attrs["domain"]
    result = [{"domain": domain}]
    if domain == "real_building" and attrs.get("style"):
        result.append(result[-1] | {"style": attrs["style"]})
        if attrs.get("building_type"):
            result.append(result[-1] | {"building_type": attrs["building_type"]})
            if attrs.get("biome_like"):
                result.append(result[-1] | {"biome_like": attrs["biome_like"]})
    elif domain == "real_terrain" and attrs.get("biome_like"):
        result.append(result[-1] | {"biome_like": attrs["biome_like"]})
    return result


def _points(db, assets, quality):
    from colorstats.analyze.color import extract_relations

    regions = {r["id"]: r for r in _read(db, "regions")}
    observations = defaultdict(list)
    for row in _read(db, "observations", eligible=True):
        if row["eligible"] and assets[row["asset_id"]]["eligible"]:
            observations[row["region_id"]].append(row)
    points = defaultdict(list)
    for rid, rows in sorted(observations.items()):
        region = regions[rid]
        row = min(rows, key=lambda r: (-r["data"]["area_ratio"], r["id"]))
        if region["label"] not in quality["supported_by_domain"].get(
            assets[row["asset_id"]]["domain"], [],
        ):
            raise ValueError("snapshotの個別ラベル品質が矛盾しています")
        points[row["asset_id"]].append({
            "role": region["label"], "region_id": rid, "area": region["data"]["area_ratio"],
            "observations": [row["data"]], "source": "region",
        })
    for row in _read(db, "groups", eligible=True):
        if not row["eligible"] or not assets[row["asset_id"]]["eligible"]:
            continue
        if row["role"] not in quality.get("group_members", {}):
            raise ValueError("snapshotの和集合品質が矛盾しています")
        data = row["data"]
        points[row["asset_id"]].append({
            "role": row["role"].split("/", 1)[1], "region_id": row["id"],
            "area": data["area_ratio"], "observations": data["observations"], "source": "union",
        })
    raw = defaultdict(list)
    for row in _read(db, "relations", eligible=True):
        if row["eligible"] and assets[row["asset_id"]]["eligible"]:
            raw[row["asset_id"]].append(row["data"])
    for aid, entries in sorted(points.items()):
        entries.sort(key=lambda r: r["region_id"])
        valid = []
        for entry in entries:
            area = entry["area"]
            color = entry["observations"][0]["observed_oklab"]["dominant"]
            if area > 0 and math.isfinite(area) and all(math.isfinite(v) for v in color):
                valid.append(entry)
                metrics = dict(zip(("L", "a", "b"), color, strict=True))
                yield aid, "palette", (entry["role"],), area, metrics
        # 和集合pairだけ、固定済み色・面積から既存co_occurs推定量を再構成する。
        for a, b in combinations(valid, 2):
            if (a["source"] == "union" or b["source"] == "union") and a["role"] != b["role"]:
                raw[aid].extend(extract_relations([a, b]))
        by_region = {e["region_id"]: e for e in valid}
        for relation in raw[aid]:
            if relation["type"] != "co_occurs":
                continue
            a, b = (by_region.get(relation[key]) for key in ("region_a", "region_b"))
            if a is None or b is None or a["role"] == b["role"]:
                continue
            area = a["area"] * b["area"]
            metrics = {k: relation[k] for k in (
                "delta_l", "delta_c", "delta_h", "delta_e_ok", "area_ratio",
            )}
            if (any(metrics[k] is None for k in metrics if k != "delta_h")
                    or area <= 0 or metrics["area_ratio"] <= 0
                    or not all(math.isfinite(v) for v in [area, *metrics.values()]
                               if v is not None)):
                continue
            yield aid, "relation", (a["role"], b["role"]), area, metrics


def aggregate(snapshot, expected_hash, settings):
    """信頼済みhashのsnapshotのみを読み、DB・画像に接続せず統計を返す。

    settingsは目標層・taxonomyの順序と親・閾値を含む。借用で実測支持は増えない。
    欠損・hash不一致・契約不一致は例外とし、部分結果を公開しない。
    """
    manifest = verify(snapshot, expected_hash)
    if manifest["taxonomy_version"] != settings["taxonomy_version"]:
        raise ValueError("taxonomy版が一致しません")
    quality = manifest["quality"]
    supported = {domain: set(labels) for domain, labels in quality["supported_by_domain"].items()}
    for role in quality.get("group_members", {}):
        domain, label = role.split("/", 1)
        supported.setdefault(domain, set()).add(label)
    parents = settings["parents"] | {
        member: role.split("/", 1)[1]
        for role, members in quality.get("group_members", {}).items() for member in members
    }
    rank = {role: index for index, role in enumerate(settings["role_order"])}
    cells = defaultdict(list)
    with duckdb.connect() as db:
        for table in ("assets", "regions", "observations", "relations", "groups", "runs"):
            db.read_parquet(str(Path(snapshot) / (table + ".parquet"))).create_view(table)
        assets = {r["id"]: r for r in _read(db, "assets")}
        assignments, unassigned = weights.assign_strata(assets, settings["strata"])
        attributes = {aid: weights.asset_attributes(asset)[0] for aid, asset in assets.items()}
        condition_sets = defaultdict(dict)
        roles = {domain: set(labels) for domain, labels in supported.items()}
        for asset in assets.values():
            domain = asset["domain"]
            if domain not in supported:
                continue
            attrs = attributes[asset["id"]]
            for condition in _conditions(attrs):
                condition_sets[domain][canonical(condition)] = condition
        for layer in settings["strata"]:
            domain = layer["attributes"]["domain"]
            for condition in _conditions(layer["attributes"]):
                condition_sets[domain][canonical(condition)] = condition
        for region in _read(db, "regions"):
            domain = assets[region["asset_id"]]["domain"]
            roles.setdefault(domain, set()).add(region["label"])
        for aid, kind, parts, area, metrics in _points(db, assets, quality):
            asset = assets[aid]
            domain = asset["domain"]
            if kind == "relation" and rank[parts[0]] > rank[parts[1]]:
                parts = parts[::-1]
                metrics = metrics | {
                    "delta_l": -metrics["delta_l"], "delta_c": -metrics["delta_c"],
                    "delta_h": (-metrics["delta_h"] + 180) % 360 - 180
                    if metrics["delta_h"] is not None else None,
                    "area_ratio": 1 / metrics["area_ratio"],
                }
            data = asset["data"]
            inferred = data["quality"].get("scene_inference", {}).get("attributes", {})
            intended = (data.get("search_parameters") or {}).get("collection_bias", {}).get(
                "intended_attributes", {},
            )
            row = {
                "unassigned_reasons": unassigned.get(asset["subject_id"], []),
                "attributes_inferred": any(v["state"] == "inferred" for v in inferred.values()),
                "intended_only": bool(set(intended) - {"domain"} - attributes[aid].keys()),
                "sha256": asset["sha256"], "subject": asset["subject_id"],
                "attributes": assignments.get(asset["subject_id"]),
                "area": area, "metrics": metrics,
            }
            attrs = attributes[asset["id"]]
            for condition in _conditions(attrs):
                cells[kind, canonical(condition), parts].append(row)
        all_runs = {r["id"]: r for r in _read(db, "runs")}
        inputs = set()
        for asset in assets.values():
            if not asset["eligible"]:
                continue
            data = asset["data"]
            inputs.update(v for k, v in data["selection"].items() if k.endswith("_run_id"))
            for field in ("subject_inference", "scene_inference"):
                if reference := data["quality"].get(field, {}).get("run_id"):
                    inputs.add(reference)
        pending = list(inputs)
        while pending:
            rid = pending.pop()
            for parent in all_runs[rid]["data"].get("input_run_ids", []):
                if parent not in inputs:
                    inputs.add(parent)
                    pending.append(parent)
        input_runs = [all_runs[rid] for rid in sorted(inputs)]
    for domain, conditions in condition_sets.items():
        pairs = list(combinations(sorted(supported[domain], key=rank.__getitem__), 2))
        for condition in conditions:
            for role in roles[domain]:
                cells["palette", condition, (role,)]
            for pair in pairs:
                cells["relation", condition, pair]
    for kind, condition, parts in list(cells):
        parent_parts = tuple(parents.get(part, part) for part in parts)
        if parent_parts != parts and len(set(parent_parts)) == len(parts):
            cells[kind, canonical({"domain": json.loads(condition)["domain"]}), parent_parts]
    resolved = {}

    def resolve(key):
        if key in resolved:
            return resolved[key]
        kind, condition_json, parts = key
        condition = json.loads(condition_json)
        rows = sorted(cells[key], key=canonical)
        row_weights, support = weights.calculate(rows, settings["strata"], condition)
        raw = distributions.summarize(rows, row_weights, kind)
        count, effective = support["subject_count"], support["effective_sample_size"]
        valid_model = all(part in supported[condition["domain"]] for part in parts)
        parent_key = None
        if len(condition) > 1:
            parent_key = kind, canonical(_conditions(condition)[-2]), parts
        else:
            parent_parts = tuple(parents.get(part, part) for part in parts)
            if parent_parts != parts and len(set(parent_parts)) == len(parts):
                parent_key = kind, condition_json, parent_parts
        parent = resolve(parent_key) if parent_key is not None else None
        coefficient = 1.
        status = "direct" if valid_model and min(count, effective) >= settings["direct_min"] else (
            "unsupported"
        )
        distribution = raw
        if (status != "direct" and valid_model and parent
                and parent["quality"]["status"] != "unsupported"):
            coefficient = (effective / (effective + settings["smoothing_strength"])
                           if min(count, effective) >= settings["mixed_min"] else 0.)
            distribution = distributions.mix(raw, parent["distribution"], coefficient)
            status = "smoothed"
        elif status != "direct":
            coefficient = 0.
            distribution = distributions.summarize([], [], kind)
        flags = []
        if min(count, effective) < settings["direct_min"]:
            flags.append("low_support")
        if status != "direct":
            flags.append(status)
        if not valid_model:
            flags.append("model_unvalidated")
        if support["unknown_images"]:
            flags.append("subject_unresolved")
        if support["missing_target_mass"] > 1e-12:
            flags.append("missing_target_mass")
        if support["max_stratum_weight"] > 5:
            flags.append("high_weight")
        for flag in ("attributes_inferred", "intended_only"):
            if any(r[flag] for r in rows):
                flags.append(flag)
        if any("license" in reason or "restricted" in reason for reason in manifest["exclusions"]):
            flags.append("license_excluded")
        diagnostics = {"raw": raw}
        for name, options in (
            ("uncorrected", {"corrected": False}), ("capped_5", {"cap": 5}),
            ("unknown_as_subject", {"corrected": False, "unknown": True}),
        ):
            sensitivity_weights, _ = weights.calculate(
                rows, settings["strata"], condition, **options,
            )
            diagnostics[name] = distributions.summarize(rows, sensitivity_weights, kind)
        unknown_rows = [r for r in rows if r["subject"] is None]
        unknown_weights, _ = weights.calculate(
            unknown_rows, settings["strata"], condition, corrected=False, unknown=True,
        )
        diagnostics["unknown_only"] = distributions.summarize(unknown_rows, unknown_weights, kind)
        parent_reference = (
            {"conditions": parent["conditions"], "target_parts": parent["target_parts"]}
            if parent is not None else None
        )
        result = {
            "conditions": condition, "target_parts": list(parts),
            "distribution": distribution | {
                "kind": kind, "estimator": "subject_partial_poststratified_appearance",
                "units": {"color": "OKLab", "delta_h": "degree", "area_ratio": "B/A"},
                "direction": "B-A" if kind == "relation" else None,
                "parent": parent_reference, "lambda": coefficient, "diagnostics": diagnostics,
            },
            **{k: support[k] for k in (
                "sample_count", "subject_count", "effective_sample_size", "weight",
            )},
            "quality": support | {
                "status": status, "flags": flags, "raw_subjects": count, "raw_n_eff": effective,
                "parent": parent_reference, "lambda": coefficient,
                "source_quality": parent["quality"]["status"] if parent else None,
                "gate_version": manifest["gate_version"], "snapshot_id": expected_hash,
                "exclusions": manifest["exclusions"],
            },
            "confidence_interval": None,
        }
        resolved[key] = result
        return result

    for key in sorted(cells):
        resolve(key)
    return {
        "snapshot_id": expected_hash, "rows": [resolved[key] for key in sorted(resolved)],
        "input_runs": input_runs, "taxonomy_version": manifest["taxonomy_version"],
    }


def prepare(claim):
    """固定payloadを再照合し、試行固有JSONを返す。DB更新は行わない。"""
    payload = claim.payload
    if claim.stage != "aggregate" or claim.asset_id is not None:
        raise ValueError("assetなしのaggregate jobが必要です")
    if config_hash(payload) != claim.config_hash:
        raise ValueError("集計設定hashが一致しません")
    data = aggregate(payload["snapshot"], payload["snapshot_id"], payload["settings"])
    target = Path(payload["output_path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{claim.token}.tmp")
    temporary.write_text(canonical(data) + "\n", encoding="utf-8")
    return Prepared(
        RunInfo("open", CODE_VERSION, data["taxonomy_version"], "aggregate", {"payload": payload}),
        data=data, files=[(temporary, target)],
    )


def register(session, run, data):
    """成功入力runと全rule_statを完了取引へ追加する。commit・外部I/Oは行わない。

    不一致はValueErrorとし、所有権とrollbackはQueueに委ねる。
    """
    if (run.stage != "aggregate" or run.config_hash != config_hash(run.parameters["payload"])
            or data["snapshot_id"] != run.parameters["payload"]["snapshot_id"]
            or run.taxonomy_version != data["taxonomy_version"]):
        raise ValueError("集計runと固定入力が一致しません")
    for record in data["input_runs"]:
        source = session.get(ProcessingRun, uuid.UUID(record["id"]))
        expected = record["data"]
        if (source is None or source.finished_at is None or source.failure_reason is not None
                or source.taxonomy_version != run.taxonomy_version
                or source.config_hash != expected["config_hash"]
                or source.code_version != expected["code_version"]
                or source.stage != record["stage"] or source.license_class != "open"
                or any(canonical(getattr(source, field)) != canonical(expected[field])
                       for field in ("parameters", "weights_hash", "model_name", "license_class"))
                or sorted(str(rid) for rid in session.scalars(select(
                    ProcessingRunInput.input_run_id,
                ).where(ProcessingRunInput.run_id == source.id))) != expected["input_run_ids"]):
            raise ValueError("snapshotの成功入力runとDBの由来が一致しません")
        session.add(ProcessingRunInput(run_id=run.id, input_run_id=source.id))
    session.add_all(RuleStat(
        processing_run_id=run.id, taxonomy_version=run.taxonomy_version,
        **(row | {"confidence_interval": null()}),
    ) for row in data["rows"])
