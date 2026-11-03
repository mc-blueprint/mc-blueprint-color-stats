"""固定snapshotと集計済みrule_statの偏り・支持範囲を報告する。"""

import math
from collections import Counter
from pathlib import Path

import duckdb

from colorstats.collect.coverage import matches
from colorstats.stats.aggregate import CODE_VERSION as AGGREGATE_VERSION
from colorstats.stats.aggregate import _read, aggregate
from colorstats.stats.snapshot import canonical, digest, verify

CODE_VERSION = "report-v1"


def _rate(numerator, denominator):
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


def _concentration(values):
    known = Counter(value for value in values if value)
    unknown = len(values) - sum(known.values())
    frequencies = [*known.values(), *([unknown] if unknown else [])]
    return {
        "counts": dict(sorted(known.items())),
        "unknown": _rate(unknown, len(values)),
        "top_share": _rate(max(known.values(), default=0), len(values)),
        "entropy_bits": -sum(n / len(values) * math.log2(n / len(values)) for n in frequencies),
    }


def _attributes(asset):
    data = asset["data"]
    return (
        (data.get("subject") or {}).get("scene_attributes", {})
        | data["scene_attributes"]
        | {"domain": asset["domain"]}
    )


def _summary(rows, provenance, target=None):
    count = len(rows)
    eligible = [r for r in rows if r["eligible"]]
    reasons = Counter(reason for r in rows for reason in r["reasons"])
    # 権利以外のsnapshot除外は解析不足・対象外domain・SHA重複の3種。
    rights = [
        r
        for r in rows
        if not set(r["reasons"])
        - {
            "missing_analysis",
            "unsupported_domain",
            "sha_duplicate",
        }
    ]
    subjects = {r["subject_id"] for r in eligible if r["subject_id"]}
    candidate = sum(not r["subject_id"] and bool(r["data"].get("candidates")) for r in rows)
    unknown = sum(not r["subject_id"] and not r["data"].get("candidates") for r in rows)
    authors, providers, sites, regions, locations, licenses, subject_ids = ([] for _ in range(7))
    for row in rows:
        data = row["data"]
        origin = provenance.get(row["id"], {})
        quality = data["quality"]
        author = quality.get("author", origin.get("author")) or ""
        authors.append(author.strip().casefold())
        providers.append(data.get("search_provider") or origin.get("site"))
        sites.append(origin.get("site"))
        subject = data.get("subject") or {}
        regions.append(subject.get("location"))
        locations.append(
            canonical(data["collected_location"]) if data.get("collected_location") else None
        )
        licenses.append(quality.get("license") or origin.get("license"))
        subject_ids.append(row["subject_id"])
    return {
        "asset_rows": count,
        "sha_distinct": len({r["sha256"] for r in rows}),
        "duplicate_rows": count - len({r["sha256"] for r in rows}),
        "eligible": _rate(len(eligible), count),
        "rights_eligible": _rate(len(rights), count),
        "analysis_eligible_before_dedup": _rate(
            sum(not set(r["reasons"]) - {"sha_duplicate"} for r in rows), count,
        ),
        "rights_eligible_sha": len({r["sha256"] for r in rights}),
        "confirmed_subjects_before": len({r["subject_id"] for r in rows if r["subject_id"]}),
        "confirmed_subjects_after": len(subjects),
        "subject_deficit": max(0, target - len(subjects)) if target is not None else None,
        "confirmed_images": _rate(sum(bool(r["subject_id"]) for r in rows), count),
        "candidate_only_images": _rate(candidate, count),
        "unknown_subject_images": _rate(unknown, count),
        "exclusions": {reason: _rate(n, count) for reason, n in sorted(reasons.items())},
        "concentration": {
            key: _concentration(values)
            for key, values in (
                ("subject", subject_ids),
                ("author", authors),
                ("provider", providers),
                ("site", sites),
                ("region", regions),
                ("shooting_location", locations),
                ("license", licenses),
            )
        },
    }


def report(snapshot, expected_hash, statistics, settings):
    """snapshotを検証・再集計し、同じrule_stat行だけから決定的な報告を返す。

    statisticsはaggregate CLIのJSON（登録対象rule_statのrowsを含む）。
    settingsも#75と同じ固定設定を渡す。DBや元画像には接続しない。
    hash・taxonomy・統計の不一致はValueError、欠損・I/O例外は呼出し側へ返す。
    本番監査やGへの受領確認をsnapshotだけから達成扱いにはしない。
    """
    manifest = verify(snapshot, expected_hash)
    recomputed = aggregate(snapshot, expected_hash, settings)
    if canonical(statistics) != canonical(recomputed):
        raise ValueError("snapshot・設定とrule_statの再計算結果が一致しません")
    with duckdb.connect() as db:
        for table in ("assets", "provenance", "runs", "observations", "relations", "groups"):
            db.read_parquet(str(Path(snapshot) / (table + ".parquet"))).create_view(table)
        assets = list(_read(db, "assets"))
        provenance = {r["asset_id"]: r["data"] for r in _read(db, "provenance")}
        runs = list(_read(db, "runs"))
        observations = {}
        for table in ("observations", "relations", "groups"):
            rows = list(_read(db, table))
            observations[table] = {
                "rows": len(rows),
                "eligible": _rate(sum(r["eligible"] for r in rows), len(rows)),
                "reasons": dict(
                    sorted(Counter(reason for r in rows for reason in r.get("reasons", [])).items())
                ),
            }
    intended, inferred = {}, {}
    conflicts, missing, mismatch, multiple, outside = [], [], [], [], []
    states = {}
    attribute_keys = sorted(
        {key for s in settings["strata"] for key in s["attributes"]} - {"domain"}
    )
    for row in assets:
        data = row["data"]
        attrs = _attributes(row)
        intent = (
            (data.get("search_parameters") or {})
            .get("collection_bias", {})
            .get(
                "intended_attributes",
                {},
            )
        )
        intended[row["id"]] = [s["id"] for s in settings["strata"] if matches(intent, s)]
        inferred[row["id"]] = [s["id"] for s in settings["strata"] if matches(attrs, s)]
        subject_attrs = (data.get("subject") or {}).get("scene_attributes", {})
        if any(
            k in subject_attrs and subject_attrs[k] != v
            for k, v in data["scene_attributes"].items()
        ):
            conflicts.append(row)
        applicable = [s for s in settings["strata"] if s["attributes"]["domain"] == row["domain"]]
        if not inferred[row["id"]]:
            (
                missing if any(set(s["attributes"]) - attrs.keys() for s in applicable) else outside
            ).append(row)
        if len(inferred[row["id"]]) > 1:
            multiple.append(row)
        if any(k in attrs and attrs[k] != v for k, v in intent.items()):
            mismatch.append(row)
        evidence = data["quality"].get("scene_inference", {}).get("attributes", {})
        for key in attribute_keys:
            state = evidence.get(key, {}).get("state")
            # 根拠stateがない既存値を新規推定成功に数えない。
            state = state or ("recorded" if key in attrs else "unknown")
            states.setdefault(key, Counter())[state] += 1
    strata = []
    for layer in settings["strata"]:
        selected = [r for r in assets if layer["id"] in inferred[r["id"]]]
        intent_rows = [r for r in assets if layer["id"] in intended[r["id"]]]
        strata.append(
            {
                "id": layer["id"],
                "attributes": layer["attributes"],
                "target_subjects": layer["subjects"],
                "inferred": _summary(selected, provenance, layer["subjects"]),
                "intended": _summary(intent_rows, provenance, layer["subjects"]),
                "intent_comparison": {
                    key: _rate(
                        len({r["id"] for r in intent_rows} & {r["id"] for r in cohort}),
                        len(intent_rows),
                    )
                    for key, cohort in (
                        ("matched", selected), ("attributes_missing", missing),
                        ("attributes_conflict", conflicts), ("mismatch", mismatch),
                        ("multiple_strata", multiple),
                    )
                },
            }
        )
    support = []
    gates = {}
    for row in statistics["rows"]:
        distribution, quality = row["distribution"], row["quality"]
        support.append(
            {
                k: row[k]
                for k in (
                    "conditions",
                    "target_parts",
                    "sample_count",
                    "subject_count",
                    "effective_sample_size",
                )
            }
            | {
                "kind": distribution["kind"],
                "units": distribution["units"],
                "direction": distribution["direction"],
                "quality": quality,
                "sensitivity": distribution["diagnostics"],
            }
        )
    for domain in ("real_building", "real_terrain"):
        candidates = [
            r for r in support if r["kind"] == "palette" and r["conditions"] == {"domain": domain}
        ]
        qualifying = [
            r["target_parts"][0]
            for r in candidates
            if r["subject_count"] >= 10
            and r["effective_sample_size"] >= 10
            and "model_unvalidated" not in r["quality"]["flags"]
        ]
        gates[domain] = {
            "passed": bool(qualifying),
            "roles": qualifying,
            "threshold": {"confirmed_subjects": 10, "subject_n_eff": 10},
            "basis": "親からの借用ではなく当該役割の直接観測支持",
        }
    all_count = len(assets)
    overall = _summary(assets, provenance)
    checks = [
        {
            "condition": 1,
            "status": "unverified",
            "reason": "固定7,607件の#66全件監査・品質評価・速度・容量の実測照合が別途必要",
        },
        {
            "condition": 2,
            "status": "unverified",
            "reason": "候補・確定・未知と属性stateは報告済み。#72再実行・誤結合監査は別途必要",
        },
        {
            "condition": 3,
            "status": "passed",
            "reason": "D15 snapshotの全hash検証と同じ設定でのrule_stat再計算が完全一致",
        },
        {
            "condition": 4,
            "status": "passed" if all(g["passed"] for g in gates.values()) else "failed",
            "reason": "建築・地形それぞれのモデル品質と直接観測subject数・n_effで判定",
        },
        {"condition": 5, "status": "passed", "reason": "全対象層・未知・除外・平滑化・支持を出力"},
        {
            "condition": 6,
            "status": "unverified",
            "reason": "単位・支持・権利の引継ぎ内容は出力済み。Gへの実際の引継ぎ確認が必要",
        },
    ]
    return {
        "snapshot_id": expected_hash,
        "code_version": CODE_VERSION,
        "aggregate_code_version": AGGREGATE_VERSION,
        "settings_hash": digest(settings),
        "statistics_hash": digest(statistics),
        "taxonomy_version": manifest["taxonomy_version"],
        "snapshot_code_version": manifest.get("code_version"),
        "snapshot_config_hash": manifest.get("config_hash"),
        "gate_version": manifest["gate_version"],
        "overall": overall,
        "strata": strata,
        "classification": {
            key: _rate(len(rows), all_count)
            for key, rows in (
                ("attributes_missing", missing),
                ("attributes_conflict", conflicts),
                ("intent_mismatch", mismatch),
                ("multiple_strata", multiple),
                ("outside_target", outside),
            )
        }
        | {
            "attribute_states": {k: dict(sorted(v.items())) for k, v in states.items()},
            "unassigned": _rate(sum(not found for found in inferred.values()), all_count),
            "stratum_counts_are_not_additive": True,
        },
        "observation_exclusions": observations,
        "snapshot_exclusions": manifest["exclusions"],
        "model_quality": manifest["quality"],
        "support": support,
        "usefulness_gates": gates,
        "processing": {
            "runs": runs,
            "snapshot_counts": manifest.get("counts", {}),
            "snapshot_bytes": sum(
                (Path(snapshot) / name).stat().st_size for name in manifest["files"]
            ),
            "scope": "snapshotに保存された選択runのみ。全量失敗・未選択runと実運用性能は未計測",
        },
        "scale_target": {
            "images": 100000,
            "achieved": overall["eligible"]["numerator"] >= 100000,
            "eligible_sha_images": overall["eligible"]["numerator"],
            "is_m3_completion_requirement": False,
        },
        "m3_checks": checks,
        "m3_complete": all(c["status"] == "passed" for c in checks),
        "handoff": {
            "distribution": "subject事後層化による外観色。母集団への無偏推定や材質色ではない",
            "units": {
                "color": "OKLab",
                "delta_h": "degree",
                "relation_delta": "B-A",
                "relation_area_ratio": "B/A",
            },
            "support": "subject基準n_eff。smoothedは親CDF混合、実測支持を増やさない",
            "rights": ("D15除外を維持。帰属・出典はsnapshotのprovenanceに保持。"
                       "パック同梱許可は別判断"),
            "pack_schema": "Gで別途確定。M3報告はパックスキーマを定義しない",
        },
    }


def markdown(data):
    """JSONと同じ分母・未確認条件・支持情報を表示する日本語Markdownを返す。"""
    lines = [
        "# M3 偏り・支持範囲レポート",
        "",
        f"- snapshot: `{data['snapshot_id']}`",
        f"- コード: {data['code_version']} / {data['aggregate_code_version']}",
        f"- taxonomy: {data['taxonomy_version']} / 設定hash: `{data['settings_hash']}`",
        f"- 統計hash: `{data['statistics_hash']}`",
        f"- M3完了: {data['m3_complete']} / 10万枚達成: {data['scale_target']['achieved']}",
        "- 層は重複し得るため合計しない。空分母の率はnull。詳細・感度分布はJSONを参照。",
        "",
        ("| 層 | 意図行数 | 属性一致行数 | SHA異なり | 重複行 | 適格/分母 | "
         "subject前→後 | 不足 | 除外理由（件数/分母） |"),
        "|---|---:|---:|---:|---:|---|---|---:|---|",
    ]
    for layer in [
        {"id": "全体", "inferred": data["overall"], "intended": data["overall"]},
        *data["strata"],
    ]:
        row = layer["inferred"]
        excluded = (
            "、".join(
                f"{k}: {v['numerator']}/{v['denominator']}" for k, v in row["exclusions"].items()
            )
            or "なし"
        )
        rate = row["eligible"]
        lines.append(
            f"| {layer['id']} | {layer['intended']['asset_rows']} | {row['asset_rows']} | "
            f"{row['sha_distinct']} | {row['duplicate_rows']} | "
            f"{rate['numerator']}/{rate['denominator']} | "
            f"{row['confirmed_subjects_before']}→{row['confirmed_subjects_after']} | "
            f"{row['subject_deficit']} | {excluded} |"
        )
    lines += [
        "", "## 収集意図に対する属性確認", "",
        "| 層 | 一致/意図行 | 属性不足/意図行 | 不一致/意図行 | 属性競合/意図行 |",
        "|---|---|---|---|---|",
    ]
    for layer in data["strata"]:
        values = [layer["intent_comparison"][key]
                  for key in ("matched", "attributes_missing", "mismatch", "attributes_conflict")]
        cells = [str(v["numerator"]) + "/" + str(v["denominator"]) for v in values]
        lines.append("| " + layer["id"] + " | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## 分類と未知",
        "",
        "```json",
        canonical(data["classification"]),
        "```",
        "",
        "## 内部有用性ゲート",
        "",
    ]
    for domain, gate in data["usefulness_gates"].items():
        lines.append(f"- {domain}: {gate['passed']}（役割: {', '.join(gate['roles']) or 'なし'}）")
    lines += [
        "",
        "## 条件・役割別支持",
        "",
        "| 条件 | 役割/pair | 種別 | 支持 | subject | n_eff | 最大重み | 欠損目標質量 |",
        "|---|---|---|---|---:|---:|---:|---:|",
    ]
    for row in data["support"]:
        quality = row["quality"]
        lines.append(
            f"| {canonical(row['conditions'])} | {'/'.join(row['target_parts'])} | "
            f"{row['kind']} | {quality['status']} | {row['subject_count']} | "
            f"{row['effective_sample_size']:.6g} | {quality['max_weight']:.6g} | "
            f"{quality['missing_target_mass']:.6g} |"
        )
    lines += ["", "## M3完成条件", ""]
    lines += [f"- 条件{c['condition']}: {c['status']} — {c['reason']}" for c in data["m3_checks"]]
    lines += ["", "## Gへの引継ぎ", ""]
    lines += [f"- {value}" for value in data["handoff"].values() if isinstance(value, str)]
    lines += ["", "## 計測範囲", "", data["processing"]["scope"], ""]
    return "\n".join(lines)
