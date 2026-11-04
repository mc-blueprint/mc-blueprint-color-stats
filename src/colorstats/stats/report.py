"""固定snapshotと集計済みrule_statの偏り・支持範囲を報告する。"""

import math
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

from colorstats.stats.aggregate import CODE_VERSION as AGGREGATE_VERSION
from colorstats.stats.aggregate import _conditions, _points, _read, aggregate
from colorstats.stats.snapshot import canonical, digest, verify
from colorstats.stats.weights import asset_attributes, assign_strata, calculate, compatible_strata

CODE_VERSION = "report-v3"
NON_RIGHTS_REASONS = {"missing_analysis", "unsupported_domain", "sha_duplicate"}


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


def _rights_eligible(asset):
    return not set(asset["reasons"]) - NON_RIGHTS_REASONS


def _summary(rows, provenance, memberships, target=None, stratum=None):
    count = len(rows)
    eligible = [r for r in rows if r["eligible"]]
    reasons = Counter(reason for r in rows for reason in r["reasons"])
    rights = [r for r in rows if _rights_eligible(r)]
    available = {r["subject_id"] for r in eligible if r["subject_id"]}
    subjects = {sid for sid in available if sid in memberships
                and (stratum is None or stratum in memberships[sid])}
    mass = (math.fsum(memberships[sid][stratum] for sid in sorted(subjects))
            if stratum is not None else len(subjects))
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
        "confirmed_subjects_after_snapshot": len(available),
        "unassigned_subjects": len(available - memberships.keys()),
        "subject_mass": mass,
        "subject_coverage": mass / target if target is not None else None,
        "subject_deficit": max(0, target - mass) if target is not None else None,
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


def _role_support(
    assets, regions, observations, groups, settings, quality, statistics, memberships, valid_roles,
):
    by_id = {row["id"]: row for row in assets}
    attributes = {row["id"]: asset_attributes(row)[0] for row in assets}
    compatible = {aid: compatible_strata(attrs, settings["strata"])
                  for aid, attrs in attributes.items()}
    by_region = {row["id"]: row for row in regions}
    recorded = defaultdict(set)
    roles = defaultdict(set)
    for domain, labels in quality["supported_by_domain"].items():
        roles[domain].update(labels)
    for row in regions:
        roles[by_id[row["asset_id"]]["domain"]].add(row["label"])
    for row in observations:
        if row["region_id"] is not None:
            region = by_region[row["region_id"]]
            domain = by_id[row["asset_id"]]["domain"]
            recorded[domain, region["label"]].add(row["asset_id"])
    unions = {}
    for key, members in quality.get("group_members", {}).items():
        domain, role = key.split("/", 1)
        roles[domain].add(role)
        recorded[domain, role] = {row["asset_id"] for row in groups if row["role"] == key}
        unions[domain, role] = {
            row["asset_id"] for row in regions
            if by_id[row["asset_id"]]["domain"] == domain and row["label"] in members
        }
    conditions = {canonical(row["conditions"]): row["conditions"] for row in statistics["rows"]}
    scopes = [("condition", None, conditions[key]) for key in sorted(conditions)]
    scopes += [("stratum", layer["id"], layer["attributes"]) for layer in settings["strata"]]
    result = []
    for scope, stratum, condition in scopes:
        domain = condition["domain"]
        selected = {aid for aid, attrs in attributes.items()
                    if (stratum in compatible[aid] if stratum is not None
                        else condition in _conditions(attrs))}
        for role in sorted(roles[domain]):
            key = domain, role
            ids = selected & recorded[key]
            unknown = (selected & unions.get(key, set())) - recorded[key]
            before = {by_id[aid]["subject_id"] for aid in ids if by_id[aid]["subject_id"]}
            after = {by_id[aid]["subject_id"] for aid in ids
                     if by_id[aid]["subject_id"] and _rights_eligible(by_id[aid])}
            unknown_after = {aid for aid in unknown if _rights_eligible(by_id[aid])}
            model_validated = (role in quality["supported_by_domain"].get(domain, [])
                               or key in unions)
            adopted = {by_id[aid]["subject_id"] for aid in selected & valid_roles[key]
                       if by_id[aid]["eligible"]
                       and by_id[aid]["subject_id"] in memberships
                       and (stratum is None or stratum in memberships[by_id[aid]["subject_id"]])}
            entry = {
                "scope": scope, "stratum": stratum, "conditions": condition, "role": role,
                "kind": "union" if key in unions else "region",
                "recorded_subjects_before_d15": None if unknown else len(before),
                "recorded_subjects_after_d15": None if unknown_after else len(after),
                "lost_subjects_d15": None if unknown else len(before - after),
                "subjects_after_analysis": len({by_id[aid]["subject_id"] for aid in ids
                                                if by_id[aid]["eligible"]
                                                and by_id[aid]["subject_id"]}),
                "adopted_subjects": len(adopted), "model_validated": model_validated,
                "adopted_subject_mass": (math.fsum(memberships[sid][stratum]
                                                   for sid in sorted(adopted))
                                         if stratum is not None else len(adopted)),
                "exclusion_reasons": dict(sorted(Counter(
                    reason for aid in ids | unknown for reason in by_id[aid]["reasons"]
                ).items())),
                "unverified_union_assets": len(unknown), "complete": not unknown,
            }
            if unknown:
                entry["reason"] = "和集合色が未保存。構成部位の存在を和集合色の支持に代用しない"
            result.append(entry)
    return result


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
        for table in (
            "assets", "provenance", "runs", "regions", "observations", "relations", "groups",
        ):
            db.read_parquet(str(Path(snapshot) / (table + ".parquet"))).create_view(table)
        assets = list(_read(db, "assets"))
        provenance = {r["asset_id"]: r["data"] for r in _read(db, "provenance")}
        runs = list(_read(db, "runs"))
        regions = list(_read(db, "regions"))
        color_observations = list(_read(db, "observations"))
        groups = list(_read(db, "groups"))
        by_id = {row["id"]: row for row in assets}
        valid_roles = defaultdict(set)
        for aid, kind, parts, _, _ in _points(db, by_id, manifest["quality"]):
            if kind == "palette":
                valid_roles[by_id[aid]["domain"], parts[0]].add(aid)
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
    assignments, assignment_reasons = assign_strata(by_id, settings["strata"])
    eligible = [row for row in assets if row["eligible"]]
    memberships, correction = {}, {}
    for domain in sorted({layer["attributes"]["domain"] for layer in settings["strata"]}):
        rows = [{"subject": row["subject_id"], "sha256": row["sha256"], "area": 1.,
                 "attributes": assignments.get(row["subject_id"]),
                 "unassigned_reasons": assignment_reasons.get(row["subject_id"], [])}
                for row in eligible if row["domain"] == domain]
        _, quality = calculate(rows, settings["strata"], {"domain": domain})
        memberships.update(quality["memberships"])
        correction[domain] = {key: quality[key] for key in (
            "subject_count", "correction_rate", "no_information_rate", "attribute_unknown_rates",
            "target_mass_coverage", "missing_target_mass", "unassigned_subjects",
        )}
    intended, inferred = {}, {}
    conflicts, missing, mismatch, multiple, outside = [], [], [], [], []
    states = {}
    attribute_keys = sorted(
        {key for s in settings["strata"] for key in s["attributes"]} - {"domain"}
    )
    for row in assets:
        data = row["data"]
        attrs, conflict = asset_attributes(row)
        intent = (
            (data.get("search_parameters") or {})
            .get("collection_bias", {})
            .get(
                "intended_attributes",
                {},
            )
        )
        intended[row["id"]] = (compatible_strata({"domain": row["domain"]} | intent,
                                                settings["strata"]) if intent else [])
        inferred[row["id"]] = compatible_strata(attrs, settings["strata"])
        if conflict:
            conflicts.append(row)
        applicable = [s for s in settings["strata"] if s["attributes"]["domain"] == row["domain"]]
        if any(set(s["attributes"]) - attrs.keys() for s in applicable):
            missing.append(row)
        if not inferred[row["id"]]:
            outside.append(row)
        if len(inferred[row["id"]]) > 1:
            multiple.append(row)
        if intent and not compatible_strata(attrs, [{
            "id": "intent", "attributes": {"domain": row["domain"]} | intent,
        }]):
            mismatch.append(row)
        evidence = data["quality"].get("scene_inference", {}).get("attributes", {})
        for key in attribute_keys:
            state = evidence.get(key, {}).get("state")
            # 根拠stateがない既存値を新規推定成功に数えない。
            state = (state or "recorded") if key in attrs else "unknown"
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
                "inferred": _summary(selected, provenance, memberships,
                                     layer["subjects"], layer["id"]),
                "intended": _summary(intent_rows, provenance, memberships,
                                     layer["subjects"], layer["id"]),
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
                "correction_rate": quality["correction_rate"],
                "no_information_rate": quality["no_information_rate"],
                "attribute_unknown_rates": quality["attribute_unknown_rates"],
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
        role_results = [
            {key: r[key] for key in (
                "target_parts", "subject_count", "effective_sample_size", "correction_rate",
                "no_information_rate", "attribute_unknown_rates",
            )} | {
                "passed": r["target_parts"][0] in qualifying,
                "quality_flags": ["weak_correction"] if r["no_information_rate"] > .5 else [],
            } for r in candidates
        ]
        gates[domain] = {
            "passed": bool(qualifying),
            "roles": qualifying,
            "threshold": {"confirmed_subjects": 10, "subject_n_eff": 10},
            "basis": "既知属性による部分層補正の主結果。親借用で観測支持を増やさない",
            "correction": role_results,
            "quality_flags": sorted({flag for r in role_results for flag in r["quality_flags"]}),
        }
    all_count = len(assets)
    overall = _summary(assets, provenance, memberships)
    rights_support = _role_support(
        assets, regions, color_observations, groups, settings, manifest["quality"],
        statistics, memberships, valid_roles,
    )
    observed_assets = {
        observation["asset_id"] for observation in color_observations
        if observation["region_id"] is not None
    }
    unobserved = sum(not _rights_eligible(row) and row["id"] not in observed_assets
                     for row in assets)
    rights_complete = not unobserved and all(row["complete"] for row in rights_support)
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
            "reason": ("建築・地形の部分層補正主結果のsubject数・n_effとモデル品質で判定。"
                       "passed は層補正の有効性を意味しない"),
            "role_results": {domain: gate["correction"] for domain, gate in gates.items()},
            "quality_flags": sorted({flag for gate in gates.values()
                                     for flag in gate["quality_flags"]}),
        },
        {"condition": 5, "status": "passed" if rights_complete else "unverified",
         "reason": ("全対象層と条件・役割別のD15前後支持を出力" if rights_complete else
                    "D15除外前の和集合色・部位観測が不足。#74の追加診断根拠が必要")},
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
            "image_unassigned": _rate(sum(not found for found in inferred.values()), all_count),
            "unassigned": _rate(sum(assignments.get(row["subject_id"]) is None
                                    for row in eligible), len(eligible)),
            "assignment_scope": "適格SHA代表画像。既知値の矛盾・対象外のみsubject全体を棄却",
            "partial_correction": correction,
            "subject_stratum_conflict": _rate(sum(
                "subject_stratum_conflict" in assignment_reasons.get(row["subject_id"], [])
                for row in eligible
            ), len(eligible)),
            "unassigned_subject_reasons": dict(sorted(Counter(
                reason for reasons in assignment_reasons.values() for reason in reasons
            ).items())),
            "stratum_counts_are_not_additive": True,
        },
        "observation_exclusions": observations,
        "snapshot_exclusions": manifest["exclusions"],
        "model_quality": manifest["quality"],
        "support": support,
        "rights_support": rights_support,
        "rights_support_scope": "保存済み色の両立subject数。層間で重複し、採用所属質量と区別",
        "unobserved_rights_excluded_assets": unobserved,
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
            "distribution": "既知属性によるsubject部分層補正の外観色分布",
            "correction": "補正率・属性別未知率・情報なし割合の分母は各条件・役割の採用subject数",
            "unknown": "unknownは周辺化する。全層両立でも既知属性が増えたとは扱わない",
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
        "- 両立件数は層間で重複する。所属質量はm_shの和、不足は目標subject数との差。",
        "- unknownは周辺化し、属性が判明したとは扱わない。詳細・感度分布はJSON参照。",
        "- 件数比率の空分母はnull。補正率・未知率等は#75の定義に従いN=0なら0。",
        "",
        ("| 層 | 意図両立行数 | 属性両立行数 | SHA異なり | 重複行 | 適格/分母 | "
         "subject前/適格/両立採用 | 所属質量 | 被覆 | 不足 | 除外理由（件数/分母） |"),
        "|---|---:|---:|---:|---:|---|---|---:|---|---:|---|",
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
            f"{row['confirmed_subjects_before']}/{row['confirmed_subjects_after_snapshot']}/"
            f"{row['confirmed_subjects_after']} | "
            f"{row['subject_mass']:.6g} | {row['subject_coverage']} | "
            f"{row['subject_deficit']} | {excluded} |"
        )
    lines += [
        "", "## 収集意図に対する属性確認", "",
        "| 層 | 両立/意図行 | 属性不足/意図行 | 非両立/意図行 | 属性競合/意図行 |",
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
        "## 内部有用性ゲート（条件4）",
        "",
    ]
    for domain, gate in data["usefulness_gates"].items():
        lines.append(f"- {domain}: {gate['passed']}（役割: {', '.join(gate['roles']) or 'なし'}）")
    lines += ["", data["m3_checks"][3]["reason"], "",
              "weak_correction は情報なし割合が過半の品質フラグで、passed の判定を変更しない。",
              ("| domain | 判定役割 | passed | subject（率の分母） | n_eff | 補正率 | "
               "情報なし割合 | 品質フラグ |"),
              "|---|---|---|---:|---:|---:|---:|---|"]
    for domain, gate in data["usefulness_gates"].items():
        for row in gate["correction"]:
            lines.append(
                f"| {domain} | {'/'.join(row['target_parts'])} | {row['passed']} | "
                f"{row['subject_count']} | {row['effective_sample_size']:.6g} | "
                f"{row['correction_rate']:.6g} | {row['no_information_rate']:.6g} | "
                f"{', '.join(row['quality_flags']) or 'なし'} |"
            )
    lines += [
        "",
        "## 条件・役割別支持",
        "",
        ("| 条件 | 役割/pair | 種別 | 支持 | subject（率の分母） | n_eff | 最大重み | "
         "欠損目標質量 | 補正率 | 情報なし割合 | 属性別未知率 |"),
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in data["support"]:
        quality = row["quality"]
        lines.append(
            f"| {canonical(row['conditions'])} | {'/'.join(row['target_parts'])} | "
            f"{row['kind']} | {quality['status']} | {row['subject_count']} | "
            f"{row['effective_sample_size']:.6g} | {quality['max_weight']:.6g} | "
            f"{quality['missing_target_mass']:.6g} | {row['correction_rate']:.6g} | "
            f"{row['no_information_rate']:.6g} | {canonical(row['attribute_unknown_rates'])} |"
        )
    lines += ["", "## 層・条件と役割別のD15前後支持", "",
              "保存済み部位色を持つ確定subject数。未保存の和集合色はnullとし、採用支持へ足さない。",
              ("| 範囲 | 役割 | D15前 | D15後 | D15で失ったsubject | 採用両立subject | "
               "採用所属質量 | 根拠不足画像 |"),
              "|---|---|---:|---:|---:|---:|---:|---:|"]
    for row in data["rights_support"]:
        scope = row["stratum"] or canonical(row["conditions"])
        cells = [str(row[key]) if row[key] is not None else "未確認" for key in (
            "recorded_subjects_before_d15", "recorded_subjects_after_d15", "lost_subjects_d15",
            "adopted_subjects", "adopted_subject_mass", "unverified_union_assets",
        )]
        lines.append(f"| {scope} | {row['role']} | " + " | ".join(cells) + " |")
    lines += ["", "## M3完成条件", ""]
    lines += [f"- 条件{c['condition']}: {c['status']} — {c['reason']}" for c in data["m3_checks"]]
    lines += ["", "## Gへの引継ぎ", ""]
    lines += [f"- {value}" for value in data["handoff"].values() if isinstance(value, str)]
    lines += ["", "## 計測範囲", "", data["processing"]["scope"], ""]
    return "\n".join(lines)
