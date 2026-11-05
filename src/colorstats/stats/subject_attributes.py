"""確定対象キーのWikidata根拠から建築の地域・年代を反映する。"""

import argparse
import json
import os
import re
import sys
import uuid
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import yaml
from sqlalchemy import create_engine, select

from colorstats.schema.models import Asset, ProcessingRun, Subject
from colorstats.stats.subjects import METHOD as SUBJECT_METHOD
from colorstats.stats.subjects import digest, subject_transaction, write_snapshot
from colorstats.stats.supplement import METHOD as SUPPLEMENT_METHOD
from colorstats.stats.wikidata import WikidataCatalog

METHOD = "subject-attributes-v1"
COLUMNS = {"region": "location", "era": "era"}
CALENDARS = {"Q1985727", "Q1985786"}


def active_claims(entity, prop):
    return [c for c in entity.get("claims", {}).get(prop, []) if c.get("rank") != "deprecated"]


def days_before_year(year, julian):
    years = year - 1
    return 365 * years + years // 4 - (0 if julian else years // 100 - years // 400)


def year_range(value):
    """年精度・粗い精度・before/afterを含む西暦年の閉区間を返す。"""
    if value.get("calendarmodel", "").rsplit("/", 1)[-1] not in CALENDARS:
        return None
    match = re.fullmatch(
        r"([+-]\d+)-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)Z", value.get("time", ""),
    )
    precision = value.get("precision", -1)
    if match is None or not 0 <= precision <= 14:
        return None
    year = int(match[1])
    if year <= 0:
        return None
    before, after = value.get("before", 0), value.get("after", 0)
    if precision >= 10:
        _, month, day, hour, minute, second = map(int, match.groups())
        if not 1 <= month <= 12:
            return None
        if precision == 10:
            start = (year - 1) * 12 + month - 1
            return (start - before) // 12 + 1, (start + after) // 12 + 1
        julian = value["calendarmodel"].endswith("/Q1985786")
        leap = year % 4 == 0 and (julian or year % 100 != 0 or year % 400 == 0)
        months = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        if not 1 <= day <= months[month - 1]:
            return None
        start = (days_before_year(year, julian) + sum(months[:month - 1]) + day - 1) * 86400
        for part, scale, threshold in ((hour, 3600, 12), (minute, 60, 13), (second, 1, 14)):
            if precision >= threshold:
                start += part * scale
        unit = {11: 86400, 12: 3600, 13: 60, 14: 1}[precision]
        bounds = ((start - before * unit) // 86400, (start + (after + 1) * unit - 1) // 86400)
        if bounds[0] < 0:
            return None
        return tuple(bisect_right(
            range(1, ordinal // 365 + 2), ordinal, key=lambda y: days_before_year(y, julian),
        ) for ordinal in bounds)
    unit = 10 ** max(0, 9 - precision)
    if precision <= 7:
        # Wikidataの世紀・千年紀は1始まり。十年は0始まり。
        lower = ((year - 1) // unit) * unit + 1
    else:
        lower = (year // unit) * unit
    return lower - before * unit, lower + unit - 1 + after * unit


def derive(entity, rules):
    """全有効claimが同じ区分を支持する場合だけinferredとする。入力は変更しない。"""
    result = {}
    countries = active_claims(entity, "P17")
    ids = [c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
           for c in countries]
    regions = {rules["countries"].get(qid) for qid in ids}
    region = next(iter(regions)) if len(regions) == 1 else None
    result["region"] = {
        "state": "inferred" if region else "unknown", "value": region,
        "reason": ("country_claim" if region else "no_country_evidence" if not countries
                   else "unmapped_country" if None in regions else "conflicting_countries"),
    }
    dates = active_claims(entity, "P571")
    intervals, eras = [], set()
    reason = "no_inception_claim"
    for claim in dates:
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        interval = year_range(value) if isinstance(value, dict) else None
        if claim.get("qualifiers"):
            reason = "qualified_inception"
            break
        if interval is None:
            reason = "unsupported_time"
            break
        intervals.append(list(interval))
        boundaries = sorted(lo for lo, _ in rules["eras"].values())[1:]
        if value["calendarmodel"].endswith("/Q1985786") and any(
            interval[0] <= boundary + 1 and interval[1] >= boundary - 1
            for boundary in boundaries
        ):
            reason = "julian_era_boundary"
            break
        matches = [name for name, (lo, hi) in rules["eras"].items()
                   if lo <= interval[0] <= interval[1] <= hi]
        if len(matches) != 1:
            reason = "era_boundary"
            break
        eras.add(matches[0])
    else:
        reason = "inception_claim" if len(eras) == 1 else (
            "conflicting_inceptions" if dates else "no_inception_claim"
        )
    era = next(iter(eras)) if reason == "inception_claim" else None
    result["era"] = {
        "state": "inferred" if era else "unknown", "value": era, "reason": reason,
        "year_ranges": intervals,
    }
    return result


def execute(engine, rules, catalog, snapshot, *, code_version, dry_run=False, cancel_run=None,
            domains=("real_building",)):
    """#72と同じ排他・1取引・新規snapshotで属性と成功runを確定する。

    domains内の確定画像を持つsubjectを対象とし、成功した対象同定runのキーだけを使う。
    既存の非NULL値は保存する。stateとclaimはrun/snapshotへ記録し、Subject列は文字列を保つ。
    dry_runはDB無更新。取消は指定runが付けた値のうち、後続runで変更されず現在も一致する
    値だけを更新前へ戻す。取消は元runの対象を使い、確定画像がなくても取り消す。
    API・出力・DBの例外は全反映をrollbackする。
    例外詳細に接続情報を含み得るため、CLI以外の呼出し元も例外型だけを表示すること。
    """
    run_id = str(uuid.uuid4())
    with subject_transaction(engine, dry_run, attributes_only=True) as session:
        subjects = session.scalars(select(Subject).where(
            Subject.domain.in_(domains),
            True if cancel_run else select(Asset.id).where(Asset.subject_id == Subject.id).exists(),
        ).order_by(Subject.id)).all()
        runs = session.scalars(select(ProcessingRun).where(
            ProcessingRun.stage == "subject", ProcessingRun.finished_at.is_not(None),
            ProcessingRun.failure_reason.is_(None),
        ).order_by(ProcessingRun.started_at, ProcessingRun.id)).all()
        bindings = defaultdict(set)
        for run in runs:
            if run.parameters.get("method") in (SUBJECT_METHOD, SUPPLEMENT_METHOD):
                for key in run.parameters.get("subject_keys", []):
                    if key["domain"] in domains and key.get("wikidata_id"):
                        bindings[key["subject_id"]].add(key["wikidata_id"])
        qids = {next(iter(bindings[str(s.id)])) for s in subjects if len(bindings[str(s.id)]) == 1}
        entities = catalog.attribute_claims(qids) if cancel_run is None else {}
        gps = defaultdict(list)
        for sid, aid, point in session.execute(select(
            Asset.subject_id, Asset.id, Asset.collected_location,
        ).where(
            Asset.subject_id.in_([s.id for s in subjects]), Asset.collected_location.is_not(None),
        )):
            gps[str(sid)].append({"asset_id": str(aid), "location": point})
        source_rows, later = {}, set()
        if cancel_run:
            source = next((r for r in runs if str(r.id) == str(cancel_run)
                           and r.parameters.get("method") == METHOD), None)
            if source is None or source.parameters.get("cancel_run"):
                raise ValueError("取消元の属性反映成功runがありません")
            saved = json.loads(Path(source.output_paths["snapshot"]).read_text(encoding="utf-8"))
            if saved["run_id"] != str(source.id) or saved["dry_run"]:
                raise ValueError("取消元snapshotが成功runと一致しません")
            source_rows = {row["subject_id"]: row for row in saved["subjects"]}
            subjects = [s for s in subjects if str(s.id) in source_rows]
            for run in runs[runs.index(source) + 1:]:
                if run.parameters.get("method") == METHOD:
                    later.update(tuple(change) for change in run.parameters["changes"])
        rows, changes = [], []
        for subject in subjects:
            sid = str(subject.id)
            ids = sorted(bindings[sid])
            entity = entities.get(ids[0]) if len(ids) == 1 else None
            if entity is None:
                attributes = {key: {"state": "unknown", "value": None, "reason": (
                    "conflicting_identity" if len(ids) > 1 else "no_wikidata_identity"
                )} for key in COLUMNS}
            else:
                attributes = derive(entity, rules)
            row = {
                "subject_id": sid, "name": subject.name, "wikidata_ids": ids,
                "evidence": entity, "asset_gps": sorted(gps[sid], key=lambda p: p["asset_id"]),
                "attributes": attributes, "before": {}, "after": {},
            }
            for key, column in COLUMNS.items():
                current = getattr(subject, column)
                row["before"][key] = current
                if cancel_run:
                    previous = source_rows.get(sid)
                    owned = previous and previous["before"][key] != previous["after"][key]
                    if owned and (sid, key) not in later and current == previous["after"][key]:
                        attributes[key] = {"state": "unknown", "value": previous["before"][key],
                                           "reason": "cancelled_run"}
                    else:
                        attributes[key] = {"state": "preserved", "value": current,
                                           "reason": "not_owned_by_run"}
                elif current is not None:
                    attributes[key] = {"state": "preserved", "value": current,
                                       "reason": "existing_value", "derived": attributes[key]}
                value = attributes[key]["value"]
                row["after"][key] = value
                if value != current:
                    changes.append([sid, key])
                    if not dry_run:
                        setattr(subject, column, value)
            rows.append(row)
        result = {
            "run_id": run_id, "dry_run": dry_run, "method": METHOD,
            "config_hash": digest(rules), "code_version": code_version,
            "cancel_run": str(cancel_run) if cancel_run else None,
            "rules": rules, "changes": changes,
            "wikidata": {"requests": dict(sorted(catalog.requests.items())),
                         "user_agent": catalog.client.policy["user_agent"]},
            "counts": {key: {
                "confirmed": sum(r["after"][key] is not None for r in rows),
                "unknown": sum(r["after"][key] is None for r in rows),
            } for key in COLUMNS},
            "reasons": {key: dict(Counter(r["attributes"][key]["reason"] for r in rows))
                        for key in COLUMNS},
            "subjects": rows,
        }
        if not dry_run:
            session.add(ProcessingRun(
                id=uuid.UUID(run_id), stage="subject", license_class="restricted",
                config_hash=result["config_hash"],
                parameters={k: v for k, v in result.items() if k != "subjects"},
                output_paths={"snapshot": str(snapshot.resolve())}, code_version=code_version,
                taxonomy_version=rules["taxonomy_version"], node="subject-attributes",
                finished_at=datetime.now(UTC),
            ))
            session.flush()
        write_snapshot(snapshot, result)
    return result


def main():
    parser = argparse.ArgumentParser(description="建築subjectの地域・年代を根拠付きで反映する")
    parser.add_argument("--rules", type=Path, default=Path("configs/subject_attributes.yaml"))
    parser.add_argument("--source-policy", type=Path, default=Path("configs/source_policy.yaml"))
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--wikidata-cache", type=Path, required=True)
    parser.add_argument("--code-version", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--cancel-run", type=uuid.UUID)
    args = parser.parse_args()
    engine = None
    try:
        rules = yaml.safe_load(args.rules.read_text(encoding="utf-8"))
        policy = yaml.safe_load(args.source_policy.read_text(encoding="utf-8"))
        catalog = WikidataCatalog(policy["sources"]["wikimedia_commons"], args.wikidata_cache,
                                  offline=args.offline)
        engine = create_engine(os.environ["DATABASE_URL"])
        result = execute(engine, rules, catalog, args.snapshot, code_version=args.code_version,
                         dry_run=args.dry_run, cancel_run=args.cancel_run)
        print(json.dumps(
            {k: result[k] for k in ("run_id", "counts", "reasons")}, ensure_ascii=False,
        ))
    except Exception as error:
        print(f"対象属性の反映に失敗しました: {type(error).__name__}", file=sys.stderr)
        return 1
    finally:
        if engine:
            engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
