"""保存済み根拠だけで対象候補と撮影時属性を補完する。通信は行わない。"""

import re
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from math import asin, cos, degrees, pi, radians, sin
from pathlib import Path

from PIL import Image
from sqlalchemy import select

from colorstats.rights import combine_license
from colorstats.schema.models import (
    Asset,
    AssetDuplicate,
    ProcessingRun,
    ProcessingRunInput,
    Subject,
    SubjectCandidate,
)
from colorstats.stats.subjects import METHOD as SUBJECT_METHOD
from colorstats.stats.subjects import (
    coordinates,
    digest,
    infer,
    metadata,
    normalize,
    subject_transaction,
    write_snapshot,
)

METHOD = "saved-evidence-v1"
UNKNOWN = (None, "", "unknown")


def solar_time(instant, latitude, longitude):
    """UTC撮影時刻とGPSから太陽高度を近似し、薄明の境界付近はunknownにする。

    年周の均時差・赤緯近似を使う。±6度の市民薄明と日の出入りの各境界に
    1度の保留帯を取り、極域の薄明をdawn/duskへ割り当てない。
    """
    instant = instant.astimezone(UTC)
    hour = instant.hour + instant.minute / 60 + instant.second / 3600
    gamma = 2 * pi / 365 * (instant.timetuple().tm_yday - 1 + (hour - 12) / 24)
    equation = 229.18 * (0.000075 + 0.001868 * cos(gamma) - 0.032077 * sin(gamma)
                        - 0.014615 * cos(2 * gamma) - 0.040849 * sin(2 * gamma))
    declination = (0.006918 - 0.399912 * cos(gamma) + 0.070257 * sin(gamma)
                   - 0.006758 * cos(2 * gamma) + 0.000907 * sin(2 * gamma)
                   - 0.002697 * cos(3 * gamma) + 0.00148 * sin(3 * gamma))
    angle = (hour * 60 + equation + 4 * longitude) % 1440 / 4 - 180
    altitude = degrees(asin(max(-1, min(1, sin(radians(latitude)) * sin(declination)
                                       + cos(radians(latitude)) * cos(declination)
                                       * cos(radians(angle))))))
    if altitude > 1:
        value = "day"
    elif altitude < -7:
        value = "night"
    elif -5 < altitude < -1 and abs(latitude) < 66:
        value = "dawn" if angle < 0 else "dusk"
    else:
        value = None
    return value, round(altitude, 4)


def exif_evidence(path):
    """ローカル画像の撮影日時・時差・GPS UTCだけを読む。読み取れない画像は保留する。"""
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            details = exif.get_ifd(34665)
            gps = exif.get_ifd(34853)
            result = {"date": details.get(36867), "offset": details.get(36881)}
            if 2 in gps and 4 in gps and gps.get(1) in {"N", "S"} and gps.get(3) in {"E", "W"}:
                result["latitude"] = sum(float(v) / 60 ** i for i, v in enumerate(gps[2]))
                result["longitude"] = sum(float(v) / 60 ** i for i, v in enumerate(gps[4]))
                if gps.get(1) == "S":
                    result["latitude"] *= -1
                if gps.get(3) == "W":
                    result["longitude"] *= -1
            if 29 in gps and 7 in gps:
                hours, minutes, seconds = map(float, gps[7])
                result["utc"] = (gps[29].replace(":", "-")
                                 + f"T{int(hours):02}:{int(minutes):02}:{int(seconds):02}+00:00")
            return result
    except (OSError, ValueError, TypeError, ZeroDivisionError, Image.DecompressionBombError):
        return {}


def scene_attributes(asset, rules, exif):
    """非unknownの既存値を保持し、同じ属性の独立根拠が矛盾すれば補完しない。"""
    raw = metadata(asset)
    ext = (asset.quality or {}).get("metadata", {}).get("extmetadata", {})
    evidence = defaultdict(list)
    patterns = {
        "season": {s: [*p, rf"\b(?:in|during) {s}$"]
                   for s, p in rules["attributes"]["season"].items()},
        "time_of_day": {s: [*p, rf"\b(?:at|by) {s}$"]
                        for s, p in rules["attributes"]["time_of_day"].items()},
    }
    patterns["time_of_day"]["day"] = [r"\b(?:in daylight|at daytime|by day)$"]
    for key, values in patterns.items():
        for value, regexes in values.items():
            for category in raw["categories"]:
                if any(re.search(pattern, category) for pattern in regexes):
                    evidence[key].append({"value": value, "basis": "commons_category",
                                          "category": category})
    point = coordinates(asset.collected_location)
    if "latitude" in exif:
        point = exif["latitude"], exif["longitude"]
    elif not point:
        point = coordinates(
            str(ext.get("GPSLatitude", {}).get("value", "")) + ","
            + str(ext.get("GPSLongitude", {}).get("value", "")),
        )
    dates = [("exif_date_gps", exif.get("date")),
             ("commons_date_gps", ext.get("DateTimeOriginal", {}).get("value"))]
    for basis, date in dates:
        match = re.match(r"^(\d{4})[-:](\d{2})[-:](\d{2})(?:[ T]|$)", normalize(date))
        if match and point and 23.44 < abs(point[0]) < 66:
            try:
                taken = datetime(*map(int, match.groups()))
            except ValueError:
                continue
            index = (taken.month % 12) // 3
            if point[0] < 0:
                index = (index + 2) % 4
            evidence["season"].append({
                "value": ("winter", "spring", "summer", "autumn")[index],
                "basis": basis, "date": match[0].strip(), "location": point,
            })
    utc = exif.get("utc")
    if not utc and exif.get("date") and exif.get("offset"):
        utc = exif["date"][:10].replace(":", "-") + "T" + exif["date"][11:] + exif["offset"]
    if utc and point:
        try:
            instant = datetime.fromisoformat(utc)
            if instant.tzinfo is not None:
                value, altitude = solar_time(instant, *point)
                if value:
                    evidence["time_of_day"].append({
                        "value": value, "basis": "exif_utc_solar", "utc": utc,
                        "location": point, "solar_altitude": altitude,
                    })
        except ValueError:
            pass
    result, states = dict(asset.scene_attributes), {}
    for key in ("season", "time_of_day"):
        found = {e["value"] for e in evidence[key]}
        current = result.get(key)
        value = next(iter(found)) if len(found) == 1 else None
        if current not in UNKNOWN:
            state, value = "preserved", current
        elif value:
            state = "inferred"
            result[key] = value
        else:
            state = "unknown"
        states[key] = {"state": state, "value": value, "evidence": evidence[key],
                       "reason": "conflicting_evidence" if len(found) > 1 else
                       "existing_value" if state == "preserved" else
                       "saved_evidence" if value else "insufficient_evidence"}
    return result, states


def execute(engine, rules, snapshot, *, code_version, dry_run=True, expected_hash=None,
            image_evidence=None):
    """#72/#99の判定で未確定だけを再評価し、属性と根拠を1取引で追記する。

    rulesは保存済みカタログを含むものを渡す。dry_runはREAD ONLY。
    image_evidenceは実画像のSHAを検証済みの、SHA→EXIF属性の保存台帳。
    指定しない場合はassetのstorage_pathを読む。
    本反映は保存した計画hashとの一致を必須とし、既存確定値を変更しない。
    snapshotは新規ファイル。DB例外の詳細は呼出し元で表示しないこと。
    """
    run_id = uuid.uuid4()
    with subject_transaction(engine, dry_run) as session:
        assets = session.scalars(select(Asset).order_by(Asset.id)).all()
        subjects = session.scalars(select(Subject).order_by(Subject.id)).all()
        previous = session.scalars(select(SubjectCandidate)).all()
        duplicates = session.scalars(select(AssetDuplicate)).all()
        runs = session.scalars(select(ProcessingRun).where(
            ProcessingRun.stage == "subject", ProcessingRun.finished_at.is_not(None),
            ProcessingRun.failure_reason.is_(None),
            ProcessingRun.parameters["method"].astext == SUBJECT_METHOD,
        )).all()
        keys = defaultdict(set)
        for run in runs:
            for key in run.parameters.get("subject_keys", []):
                keys[key["domain"], key["key"]].add(uuid.UUID(key["subject_id"]))
        rows, catalog = infer(assets, subjects, duplicates, previous, rules,
                              verified_runs={str(r.id): r.config_hash for r in runs},
                              verified_keys=keys)
        by_id = {str(a.id): a for a in assets}
        plan = []
        for row in rows:
            asset = by_id[row["asset_id"]]
            exif = (image_evidence.get(asset.sha256, {}) if image_evidence is not None
                    else exif_evidence(asset.storage_path))
            attrs, states = scene_attributes(asset, rules, exif)
            # 既存のカテゴリ導出も利用するが、根拠が矛盾する撮影時属性は採用しない。
            for key, value in row["scene_attributes"].items():
                if key not in states and attrs.get(key) in UNKNOWN:
                    attrs[key] = value
                    states[key] = row["scene_evidence"][key]
            sid = str(asset.subject_id) if asset.subject_id else row["subject_id"]
            plan.append({"asset_id": str(asset.id), "before_subject": str(asset.subject_id)
                         if asset.subject_id else None, "subject_id": sid,
                         "before": asset.scene_attributes, "after": attrs,
                         "attributes": states, "identity_reasons": row["reasons"],
                         "identity_evidence": row["candidates"] if not asset.subject_id else {}})
        plan_hash = digest(plan)
        if not dry_run and expected_hash != plan_hash:
            raise ValueError("補完計画が事前確認と一致しません")
        changed = [r for r in plan if r["before"] != r["after"]
                   or r["before_subject"] != r["subject_id"]]
        result = {"method": METHOD, "run_id": str(run_id), "dry_run": dry_run,
                  "config_hash": digest(rules), "code_version": code_version,
                  "image_evidence_hash": digest(image_evidence),
                  "subject_keys": [{"subject_id": str(sid), "domain": target["domain"],
                                    "key": target["key"],
                                    **({"wikidata_id": target["wikidata_id"]}
                                       if target.get("wikidata_id") else {})}
                                   for sid, target in catalog.items()],
                  "plan_hash": plan_hash, "changes": len(changed),
                  "confirmed_images": sum(r["before_subject"] != r["subject_id"] for r in plan),
                  "attribute_changes": dict(Counter(
                      key for r in plan for key in r["after"]
                      if r["after"][key] != r["before"].get(key))),
                  "basis_counts": dict(Counter(
                      e["basis"] for r in plan for k, s in r["attributes"].items()
                      if s["state"] == "inferred" for e in s.get("evidence", []))),
                  "assets": plan}
        if not dry_run and changed:
            known = {str(s.id) for s in subjects}
            for sid in sorted({r["subject_id"] for r in changed} - known - {None}):
                target = catalog[uuid.UUID(sid)]
                session.add(Subject(id=uuid.UUID(sid), name=target["name"],
                                    domain=target["domain"],
                                    taxonomy_version=rules["taxonomy_version"],
                                    scene_attributes={}))
            session.flush()
            parents = set()
            for row in changed:
                asset = by_id[row["asset_id"]]
                for key in ("subject_inference", "scene_inference"):
                    if reference := asset.quality.get(key, {}).get("run_id"):
                        parents.add(reference)
                asset.subject_id = uuid.UUID(row["subject_id"]) if row["subject_id"] else None
                asset.scene_attributes = row["after"]
                asset.quality = dict(asset.quality) | {"scene_inference": {
                    "method": METHOD, "run_id": str(run_id), "config_hash": result["config_hash"],
                    "attributes": row["attributes"],
                    "previous": asset.quality.get("scene_inference"),
                }}
                if row["before_subject"] != row["subject_id"]:
                    asset.quality = dict(asset.quality) | {"subject_inference": {
                        "method": METHOD, "run_id": str(run_id), "state": "confirmed",
                        "config_hash": result["config_hash"],
                        "reasons": row["identity_reasons"],
                    }}
            session.add(ProcessingRun(
                id=run_id, stage="subject", license_class=combine_license(
                    *(by_id[r["asset_id"]].license_class for r in changed)),
                config_hash=result["config_hash"], parameters={k: v for k, v in result.items()
                                                              if k != "assets"},
                output_paths={"snapshot": str(Path(snapshot).resolve())}, code_version=code_version,
                taxonomy_version=rules["taxonomy_version"], node="saved-evidence",
                finished_at=datetime.now(UTC),
            ))
            session.flush()
            for parent in sorted(parents):
                session.add(ProcessingRunInput(run_id=run_id, input_run_id=uuid.UUID(parent)))
        write_snapshot(snapshot, result)
    return result
