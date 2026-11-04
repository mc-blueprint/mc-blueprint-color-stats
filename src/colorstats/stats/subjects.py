"""保存済み根拠から対象と属性を推定する。画像の類似を同一対象とみなさない。"""

import hashlib
import html
import json
import math
import re
import unicodedata
import uuid
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from colorstats.schema.models import Asset, AssetDuplicate, ProcessingRun, Subject, SubjectCandidate

METHOD = "subject-rules-v1"
NAMESPACE = uuid.UUID("e87d5f5d-09eb-53e5-82aa-e7d465bd385c")


@contextmanager
def subject_transaction(engine, dry_run, *, attributes_only=False):
    """対象同定と属性反映の排他・読取り専用取引を共有する。"""
    with Session(engine) as session, session.begin():
        if dry_run:
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        else:
            session.execute(text("SELECT pg_advisory_xact_lock(29, 1)"))
            tables = "subject" if attributes_only else "subject, subject_candidate, asset"
            session.execute(text(f"LOCK TABLE {tables} IN SHARE ROW EXCLUSIVE MODE"))
        yield session


def write_snapshot(snapshot, result):
    """既存ファイルを上書きせず、成功runの根拠を書き出す。"""
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    with snapshot.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def normalize(value):
    """表記だけを正規化する。別棟・方角・地名は除去しない。"""
    value = html.unescape(re.sub(r"<[^>]*>", " ", value or ""))
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def name_key(value):
    value = normalize(value).removeprefix("file:")
    value = re.sub(r"\.(?:jpe?g|png|tiff?|webp)$", "", value)
    return re.sub(r"(?:[ _-]+\d{3,}|[ _-]+\d{4}-\d{2}-\d{2})$", "", value).strip()


def metadata(asset):
    quality = asset.quality or {}
    saved = quality.get("metadata") or {}
    categories = sorted({
        normalize(c["title"]).removeprefix("category:")
        for c in saved.get("categories", [])
    })
    description = quality.get("description") or (
        saved.get("extmetadata", {}).get("ImageDescription", {}).get("value", "")
    )
    return {
        "title": asset.collected_title,
        "description": description,
        "categories": categories,
        "location": asset.collected_location,
    }


def coordinates(value):
    if not value:
        return None
    try:
        lat, lon = map(float, value.split(","))
        if math.isfinite(lat) and math.isfinite(lon) and abs(lat) <= 90 and abs(lon) <= 180:
            return lat, lon
    except (ValueError, TypeError):
        pass
    return None


def distance(a, b):
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat, dlon = lat2 - lat1, math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(min(1, h)))


def multiple_targets(words, identity_hits, rules):
    value = " ".join(words)
    value = re.sub(r"\bbetween\s+(?:the years?\s+)?\d{3,4}\s+and\s+\d{3,4}\b", "", value)
    value = re.sub(
        r"\bbetween\s+(?:the\s+)?(?:individual\s+|two\s+|adjacent\s+)?"
        r"(?:windows|columns|pillars|beams|floors|arches)\b", "", value,
    )
    return len(identity_hits) > 1 or bool(re.search(rules["multiple_pattern"], value, re.I))


def infer(
    assets, subjects, duplicates, previous, rules, *, verified_runs=None, verified_keys=None,
    reconsidered=None,
):
    """入力を変更せず、全assetの状態・候補・根拠と必要なsubjectを返す。

    confidenceはルールのスコアであり確率ではない。自動キーのGPSはP625と照合し、
    SHA群に異なる対象の根拠がある場合は既存確定値だけを保持する。
    """
    by_id = {a.id: a for a in assets}
    subject_by_id = {s.id: s for s in subjects}
    verified_runs = verified_runs or {}
    verified_keys = verified_keys or {}
    reconsidered = reconsidered or {}
    catalog = {}
    subject_patterns = defaultdict(list)
    for subject in subjects:
        key = name_key(subject.name)
        if key:
            subject_patterns[subject.domain].append((
                subject, re.compile(rf"(?<!\w){re.escape(key)}(?!\w)"),
            ))
    alias_patterns = {}
    category_index = defaultdict(list)
    for target in rules["subjects"]:
        key = (target["domain"], target["key"])
        ids = {
            sid for sid in verified_keys.get(key, [])
            if sid in subject_by_id and subject_by_id[sid].domain == target["domain"]
        }
        for candidate in previous:
            proof = candidate.evidence
            basis = proof.get("basis", {})
            subject = subject_by_id.get(candidate.subject_id)
            source = by_id.get(candidate.asset_id)
            if (
                subject and source and subject.domain == source.domain == target["domain"]
                and subject.id == uuid.uuid5(NAMESPACE, ":".join(key))
                and proof.get("method") == METHOD and proof.get("target_key") == target["key"]
                and proof.get("run_id") in verified_runs
                and verified_runs[proof["run_id"]] == proof.get("config_hash")
                and basis.get("strong") and basis.get("key") == target["key"]
                and set(map(normalize, basis.get("names", [])))
                & set(map(normalize, target["aliases"]))
                and set(basis.get("categories", [])) & set(map(normalize, target["categories"]))
            ):
                ids.add(subject.id)
        if len(ids) > 1:
            raise ValueError("確認済み対象キーに複数のsubjectがあります")
        sid = next(iter(ids)) if ids else uuid.uuid5(NAMESPACE, ":".join(key))
        if not ids and sid in subject_by_id:
            raise ValueError("決定的UUIDに対応する確認済み対象キーがありません")
        catalog[sid] = target
        alias_patterns[sid] = [
            (name, re.compile(rf"(?<!\w){re.escape(normalize(name))}(?!\w)"))
            for name in target["aliases"]
        ]
        for category in target["categories"]:
            category_index[(target["domain"], normalize(category))].append(sid)
    decisions = {}
    sha_groups = defaultdict(list)
    positions = defaultdict(list)
    for asset in sorted(assets, key=lambda a: str(a.id)):
        raw = metadata(asset)
        collection_assignment = (
            asset.subject_id
            and (asset.search_parameters or {}).get("collection_bias")
            and (asset.quality or {}).get("subject_inference", {}).get("method") != METHOD
        )
        words = [normalize(raw["title"]), normalize(raw["description"])]
        candidates = {}
        for sid, target in catalog.items():
            if target["domain"] != asset.domain:
                continue
            matched_names = [
                n for n, pattern in alias_patterns[sid] if any(pattern.search(w) for w in words)
            ]
            matched_categories = [
                c for c in raw["categories"]
                if sid in category_index.get((asset.domain, c), [])
            ]
            automatic = set(matched_categories) & set(target.get("automatic_categories", []))
            point = coordinates(raw["location"])
            target_point = target.get("coordinates")
            location_match = bool(
                automatic and point and target_point
                and distance(point, target_point) <= rules["max_camera_span_km"][asset.domain] / 2
            )
            location_conflict = bool(automatic and point and target_point and not location_match)
            strong = bool(
                matched_categories and (matched_names or location_match) and not location_conflict
                and not target.get("candidate_only")
            )
            if point and matched_categories and (matched_names or location_match):
                positions[str(sid)].append((asset.id, point))
            if matched_names or matched_categories:
                candidates[str(sid)] = {
                    "key": target["key"], "names": matched_names,
                    "categories": matched_categories,
                    "strong": strong, "score": 0.95 if strong else 0.5,
                    **({
                        "wikidata_id": target["wikidata_id"],
                        "coordinates": target_point, "location_match": location_match,
                        "location_conflict": location_conflict,
                        "granularity": target.get("granularity"),
                        "origin": (
                            "automatic" if target["key"].startswith("wikidata:") else "manual"
                        ),
                    } if target.get("wikidata_id") else {"origin": "manual"}),
                }
        identity_hits = set(candidates)
        for subject, pattern in subject_patterns[asset.domain]:
            if any(pattern.search(w) for w in words):
                if subject.id not in catalog and not normalize(subject.name).startswith("file:"):
                    identity_hits.add(str(subject.id))
                candidates.setdefault(str(subject.id), {
                    "key": str(subject.id), "names": [subject.name], "categories": [],
                    "strong": False, "score": 0.4,
                })
        strong = [sid for sid, e in candidates.items() if e["strong"]]
        ambiguous = {
            c: rules["ambiguous_categories"][c] for c in raw["categories"]
            if c in rules.get("ambiguous_categories", {})
        }
        multiple = bool(ambiguous) or multiple_targets(words, identity_hits, rules) or any(
            target["domain"] != asset.domain
            and set(raw["categories"]) & set(target.get("automatic_categories", []))
            for target in catalog.values()
        )
        proposed = strong[0] if len(strong) == 1 and not multiple else None
        reasons = ["multiple_targets"] if multiple else []
        if any(
            e.get("granularity", {}).get("state") == "coarse"
            for e in candidates.values() if e.get("granularity")
        ):
            reasons.append("target_granularity")
        if any(e.get("location_conflict") for e in candidates.values()):
            proposed = None
            reasons.append("location_conflict")
        decisions[str(asset.id)] = {
            "asset_id": str(asset.id),
            "subject_id": (
                str(asset.subject_id)
                if asset.subject_id and not collection_assignment
                and str(asset.id) not in reconsidered
                else None
            ),
            "previous_subject_id": str(asset.subject_id) if asset.subject_id else None,
            "identity_targets": sorted(identity_hits),
            "proposed": proposed, "candidates": candidates, "reasons": reasons,
            "input": raw, "sha256": asset.sha256, "domain": asset.domain,
            **({"ambiguous_categories": ambiguous} if ambiguous else {}),
        }
        sha_groups[(asset.domain, asset.sha256)].append(str(asset.id))
    # 基準点からの直径を保守的に制限し、近接点の連鎖で対象を拡大しない。
    for sid, points in positions.items():
        limit = rules["max_camera_span_km"][catalog[uuid.UUID(sid)]["domain"]]
        anchor = points[0][1]
        if any(distance(anchor, point) > limit / 2 for _, point in points[1:]):
            for decision in decisions.values():
                if decision["proposed"] == sid:
                    decision["proposed"] = None
                    decision["reasons"].append("location_conflict")
    for candidate in previous:
        row = decisions.get(str(candidate.asset_id))
        subject = next((s for s in subjects if s.id == candidate.subject_id), None)
        if row and subject and subject.domain == row["domain"]:
            # 自分の前回出力を新たな根拠として取り込まない。
            baseline = candidate.evidence
            if baseline.get("method") == METHOD:
                baseline = baseline.get("external_evidence")
                if not baseline:
                    continue
            evidence = row["candidates"].setdefault(str(candidate.subject_id), {
                "key": str(candidate.subject_id), "strong": False,
                "score": candidate.confidence,
            })
            evidence["previous"] = baseline
    for group in sha_groups.values():
        ids = {
            sid for aid in group for sid in
            (decisions[aid]["subject_id"], decisions[aid]["proposed"]) if sid
        }
        identities = {sid for aid in group for sid in decisions[aid]["identity_targets"]}
        conflicts = sorted(ids | identities) if len(ids | identities) > 1 else []
        blocked = any(
            r in ("multiple_targets", "location_conflict", "target_granularity")
            for aid in group for r in decisions[aid]["reasons"]
        )
        for aid in group:
            row = decisions[aid]
            if blocked:
                row["proposed"] = None
            if conflicts:
                row["proposed"] = None
                row["reasons"].append("sha_conflict")
                row["sha_conflicts"] = {"targets": conflicts, "assets": sorted(group)}
            elif len(ids) == 1 and not blocked:
                row["proposed"] = next(iter(ids))
            for sid in ids | identities:
                row["candidates"].setdefault(sid, {
                    "key": sid, "strong": False, "score": 1.0 if sid in ids else 0.4,
                    "sha256": row["sha256"],
                    "sha_support": [
                        source for source in group if decisions[source]["subject_id"] == sid
                        or decisions[source]["proposed"] == sid
                    ],
                })
    for pair in duplicates:
        if pair.method != "phash":
            continue
        for a, b in ((pair.asset_a, pair.asset_b), (pair.asset_b, pair.asset_a)):
            row, other = decisions.get(str(a)), decisions.get(str(b))
            if row and other and row["domain"] == other["domain"]:
                sid = other["subject_id"] or other["proposed"]
                if sid:
                    row["candidates"].setdefault(sid, {
                        "key": sid, "strong": False, "score": pair.confidence,
                        "phash_asset": str(b),
                    })
    for row in decisions.values():
        original = row["subject_id"]
        if original:
            row["reasons"].append("existing_confirmed")
            if row["proposed"] and row["proposed"] != original:
                row["reasons"].append("existing_conflict")
        else:
            row["subject_id"] = row["proposed"]
        if row["asset_id"] in reconsidered and row["subject_id"] != reconsidered[row["asset_id"]]:
            row["subject_id"] = None
            row["reasons"].append("previous_assignment_revoked")
        row.pop("proposed")
        row["state"] = (
            "confirmed" if row["subject_id"] else "candidate" if row["candidates"] else "unknown"
        )
        if not row["reasons"]:
            row["reasons"] = [
                "independent_evidence_or_sha" if row["subject_id"]
                else "insufficient_evidence" if row["candidates"] else "no_identity_evidence"
            ]
        asset = by_id[uuid.UUID(row["asset_id"])]
        row["scene_attributes"], row["scene_evidence"] = scene(asset, row, rules, catalog)
    return list(decisions.values()), catalog


def scene(asset, decision, rules, catalog):
    result = dict(asset.scene_attributes)
    prior = (asset.quality or {}).get("scene_inference", {})
    if prior.get("method") == METHOD:
        for key, item in prior["attributes"].items():
            if item["state"] == "inferred" and result.get(key) == item["value"]:
                result.pop(key, None)
    evidence = {}
    raw = decision["input"]
    categories = raw["categories"]
    for attribute, values in rules["attributes"].items():
        found = {}
        for value, patterns in values.items():
            matched = [c for c in categories if any(re.search(p, c) for p in patterns)]
            if matched:
                found[value] = matched
        sid = decision["subject_id"]
        # 対象自体の恒久属性だけを利用し、季節・時刻を他画像から伝播しない。
        if sid and uuid.UUID(sid) in catalog:
            target = catalog[uuid.UUID(sid)]
            if value := target.get("attributes", {}).get(attribute):
                found.setdefault(value, []).append("subject:" + target["key"])
        if attribute in result:
            evidence[attribute] = {"state": "preserved", "candidates": found}
        elif len(found) == 1:
            value = next(iter(found))
            result[attribute] = value
            evidence[attribute] = {"state": "inferred", "value": value, "sources": found[value]}
        else:
            evidence[attribute] = {
                "state": "conflict" if found else "unknown", "candidates": found,
            }
    return result, evidence


def execute(
    engine, rules, snapshot, *, code_version, dry_run=False, reconsider_run=None, wikidata=None,
):
    """1取引で全件の根拠と成功runを確定する。snapshotは新規パスを指定する。

    dry_runはDBへ一切書き込まない。スナップショットの書込み失敗もDBをrollbackする。
    wikidata指定時は保存済みカテゴリからカタログを追加し、取得失敗でも反映しない。
    初回取得はdry-runで済ませ、本実行では同じキャッシュをofflineで使用する。
    失敗後に残ったファイルは成功runから参照されないため、成功結果として扱わない。
    接続先の例外詳細（認証情報を含み得る）は呼出し側で表示しないこと。
    reconsider_run指定時は、その成功runが新規に付け、現在も保持されている関連付けだけを
    再評価する。対象run以前の確定や、その後に他の処理が変更した関連付けは保持する。
    """
    run_id = uuid.uuid4()
    with subject_transaction(engine, dry_run) as session:
        assets = session.scalars(select(Asset).order_by(Asset.id)).all()
        if wikidata is not None:
            categories = {
                c["title"].removeprefix("Category:")
                for asset in assets
                for c in (asset.quality or {}).get("metadata", {}).get("categories", [])
            }
            rules = wikidata.build(categories, rules)
        config_hash = digest(rules)
        subjects = session.scalars(select(Subject).order_by(Subject.id)).all()
        duplicates = session.scalars(select(AssetDuplicate)).all()
        previous = session.scalars(select(SubjectCandidate)).all()
        successful_runs = session.scalars(select(ProcessingRun).where(
            ProcessingRun.stage == "subject", ProcessingRun.finished_at.is_not(None),
            ProcessingRun.failure_reason.is_(None),
            ProcessingRun.parameters["method"].astext == METHOD,
        )).all()
        verified_runs = {str(run.id): run.config_hash for run in successful_runs}
        verified_keys = defaultdict(set)
        for run in successful_runs:
            for binding in run.parameters.get("subject_keys", []):
                key = (binding["domain"], binding["key"])
                verified_keys[key].add(uuid.UUID(binding["subject_id"]))
        reconsidered = {}
        preserved_prior = 0
        if reconsider_run:
            source_run = session.get(ProcessingRun, uuid.UUID(str(reconsider_run)))
            if (
                source_run is None or str(source_run.id) not in verified_runs
                or not source_run.output_paths.get("snapshot")
            ):
                raise ValueError("再評価元の成功runがありません")
            source_snapshot = json.loads(
                Path(source_run.output_paths["snapshot"]).read_text(encoding="utf-8")
            )
            if source_snapshot["run_id"] != str(source_run.id):
                raise ValueError("再評価元のスナップショットがrunと一致しません")
            source_rows = {r["asset_id"]: r for r in source_snapshot["assets"]}
            for asset in assets:
                row = source_rows.get(str(asset.id))
                current = (asset.quality or {}).get("subject_inference", {})
                if (
                    not row or not asset.subject_id or str(asset.subject_id) != row["subject_id"]
                    or current.get("run_id") != str(source_run.id)
                ):
                    continue
                assigned_here = (
                    row["previous_subject_id"] is None if "previous_subject_id" in row
                    else "existing_confirmed" not in row["reasons"]
                )
                if assigned_here:
                    reconsidered[str(asset.id)] = str(asset.subject_id)
                else:
                    preserved_prior += 1
        rows, catalog = infer(
            assets, subjects, duplicates, previous, rules,
            verified_runs=verified_runs, verified_keys=verified_keys, reconsidered=reconsidered,
        )
        result = {
            "run_id": str(run_id), "dry_run": dry_run, "method": METHOD,
            "config_hash": config_hash, "code_version": code_version,
            "subject_keys": [
                {
                    "subject_id": str(sid), "domain": target["domain"], "key": target["key"],
                    **({"wikidata_id": target["wikidata_id"]} if target.get("wikidata_id") else {}),
                }
                for sid, target in catalog.items()
            ],
            "reconsider_run": str(reconsider_run) if reconsider_run else None,
            "reconsidered_assignments": len(reconsidered),
            "preserved_prior_assignments": preserved_prior,
            "revoked_assignments": sum("previous_assignment_revoked" in r["reasons"] for r in rows),
            "counts": {state: sum(r["state"] == state for r in rows)
                       for state in ("confirmed", "candidate", "unknown")},
            "reasons": dict(Counter(reason for r in rows for reason in r["reasons"])),
            "attributes": {
                key: dict(Counter(r["scene_evidence"][key]["state"] for r in rows))
                for key in rules["attributes"]
            },
            "wikidata": rules.get("wikidata"),
            "confirmed_subjects": {
                domain: len({r["subject_id"] for r in rows
                             if r["domain"] == domain and r["subject_id"]})
                for domain in ("real_building", "real_terrain")
            },
            "origins": dict(Counter(
                row["candidates"].get(row["subject_id"], {}).get("origin", "preserved_or_sha")
                for row in rows if row["subject_id"]
            )),
            "assets": rows,
        }
        if not dry_run:
            known = {s.id for s in subjects}
            used = {uuid.UUID(sid) for row in rows for sid in row["candidates"]}
            used |= {uuid.UUID(r["subject_id"]) for r in rows if r["subject_id"]}
            for sid in sorted(used - known, key=str):
                target = catalog[sid]
                session.add(Subject(
                    id=sid, name=target["name"], domain=target["domain"],
                    taxonomy_version=rules["taxonomy_version"], scene_attributes={},
                ))
            session.flush()
            session.execute(delete(SubjectCandidate).where(
                SubjectCandidate.evidence["method"].astext == METHOD,
            ))
            for row in rows:
                asset = session.get(Asset, uuid.UUID(row["asset_id"]))
                asset.subject_id = uuid.UUID(row["subject_id"]) if row["subject_id"] else None
                asset.scene_attributes = row["scene_attributes"]
                asset.quality = {
                    **asset.quality,
                    "subject_inference": {
                        "method": METHOD, "state": row["state"], "reasons": row["reasons"],
                        "config_hash": config_hash, "run_id": str(run_id),
                    },
                    "scene_inference": {
                        "method": METHOD, "config_hash": config_hash, "run_id": str(run_id),
                        "attributes": row["scene_evidence"],
                    },
                }
                for sid, evidence in row["candidates"].items():
                    session.merge(SubjectCandidate(
                        asset_id=asset.id, subject_id=uuid.UUID(sid), confidence=evidence["score"],
                        evidence={
                            "method": METHOD, "asset_id": str(asset.id),
                            "target_key": evidence["key"],
                            "config_hash": config_hash, "run_id": str(run_id), "basis": evidence,
                            "external_evidence": evidence.get("previous"),
                        },
                    ))
            session.add(ProcessingRun(
                id=run_id, stage="subject",
                license_class=(
                    "open" if all(a.license_class == "open" for a in assets) else "restricted"
                ), config_hash=config_hash,
                parameters={k: v for k, v in result.items() if k != "assets"},
                output_paths={"snapshot": str(snapshot.resolve())}, code_version=code_version,
                taxonomy_version=rules["taxonomy_version"], node="subject",
                finished_at=datetime.now(UTC),
            ))
            session.flush()
        write_snapshot(snapshot, result)
    return result
