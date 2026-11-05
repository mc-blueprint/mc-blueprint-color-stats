"""保存済み根拠だけで対象候補と撮影時属性を補完する。通信は行わない。"""

import json
import re
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from math import asin, cos, degrees, pi, radians, sin
from pathlib import Path
from types import SimpleNamespace

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
from colorstats.stats.subjects import scene as category_scene

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


def capture_date(value):
    """日が一意のEXIF/ISO撮影日時だけを読む。期間・部分日付・説明文は受理しない。"""
    value = normalize(value)
    if not re.fullmatch(
        r"\d{4}[-:]\d{2}[-:]\d{2}(?:[ t]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?"
        r"(?:z|[+-]\d{2}:\d{2})?)?", value,
    ):
        return None
    try:
        return datetime.fromisoformat(value[:10].replace(":", "-") + value[10:].upper())
    except ValueError:
        return None


def nonphotographic(asset):
    """保存カテゴリが絵画・描画等の作品を示す場合、実景の撮影属性に使わない。"""
    return any(re.search(r"\b(paintings?|drawings?|lithographs?|engravings?|etchings?)\b", c)
               for c in metadata(asset)["categories"])


def scene_attributes(asset, rules, exif, *, mutable=()):
    """撮影根拠を一括照合する。自身の先行推定は再評価し、それ以前の確定値は保持する。

    保存日時はsource=exifか、EXIF撮影日との一致がある場合だけ撮影根拠とする。
    UTCが一方だけならその根拠を使い、両方あれば1秒の丸め幅で一致を必須とする。
    不正な日時・矛盾・非写真は理由付きunknown。mutableは訂正所有権を確認済みの属性。
    """
    raw = metadata(asset)
    ext = (asset.quality or {}).get("metadata", {}).get("extmetadata", {})
    evidence = defaultdict(list)
    blocked = {}
    mutable = set(mutable)
    prior = (asset.quality or {}).get("scene_inference", {})
    checked = set()
    protected = set()
    while prior.get("method") == METHOD:
        for key, state in prior.get("attributes", {}).items():
            if key not in checked and (
                state["state"] == "inferred" or key in prior.get("owned_attributes", [])
            ):
                if state.get("value") == asset.scene_attributes.get(key):
                    mutable.add(key)
                else:
                    protected.add(key)
            checked.add(key)
        prior = prior.get("previous") or {}
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
        point = coordinates(f"{exif['latitude']},{exif['longitude']}")
    elif not point:
        point = coordinates(
            str(ext.get("GPSLatitude", {}).get("value", "")) + ","
            + str(ext.get("GPSLongitude", {}).get("value", "")),
        )
    original = capture_date(exif.get("date"))
    saved = ext.get("DateTimeOriginal", {})
    saved_date = capture_date(saved.get("value"))
    trusted_saved = saved.get("source") == "exif" or (
        original is not None and saved_date is not None and original.date() == saved_date.date())
    if exif.get("date") and original is None:
        blocked["season"] = "ambiguous_capture_date"
    if saved.get("source") == "exif" and saved.get("value") and saved_date is None:
        blocked["season"] = "ambiguous_capture_date"
    if original is not None and saved_date is not None and original.date() != saved_date.date():
        blocked["season"] = "conflicting_capture_dates"
    dates = [("exif_date_gps", original)]
    if trusted_saved:
        dates.append(("commons_date_gps", saved_date))
    for basis, taken in dates:
        if taken is not None and point and 23.44 < abs(point[0]) < 66:
            index = (taken.month % 12) // 3
            if point[0] < 0:
                index = (index + 2) % 4
            evidence["season"].append({
                "value": ("winter", "spring", "summer", "autumn")[index],
                "basis": basis, "date": taken.date().isoformat(), "location": point,
            })
    clocks = {}
    if exif.get("utc"):
        clocks["gps_utc"] = capture_date(exif["utc"])
    if original is not None and original.tzinfo is not None:
        clocks["capture_embedded_offset"] = original
    if exif.get("offset"):
        clocks["capture_offset"] = capture_date(
            (original.replace(tzinfo=None).isoformat() if original is not None else "")
            + exif["offset"])
    if any(t is None or t.tzinfo is None for t in clocks.values()):
        blocked["time_of_day"] = "invalid_utc_evidence"
    elif clocks:
        instants = [t.astimezone(UTC) for t in clocks.values()]
        if (max(instants) - min(instants)).total_seconds() > 1:
            blocked["time_of_day"] = "conflicting_utc_evidence"
        elif point:
            for source, instant in clocks.items():
                value, altitude = solar_time(instant, *point)
                if value:
                    evidence["time_of_day"].append({
                        "value": value, "basis": "exif_utc_solar", "clock": source,
                        "utc": instant.astimezone(UTC).isoformat(),
                        "location": point, "solar_altitude": altitude,
                    })
                else:
                    blocked["time_of_day"] = "solar_boundary"
    if nonphotographic(asset):
        blocked.update({key: "nonphotographic_content" for key in ("season", "time_of_day")})
    result, states = dict(asset.scene_attributes), {}
    for key in ("season", "time_of_day"):
        found = {e["value"] for e in evidence[key]}
        current = result.get(key)
        value = next(iter(found)) if len(found) == 1 and key not in blocked else None
        if key not in mutable and (current not in UNKNOWN or key in protected):
            state, value = "preserved", current
        elif value:
            state = "inferred"
            result[key] = value
        else:
            state = "unknown"
            if key in mutable:
                result.pop(key, None)
        states[key] = {"state": state, "value": value, "evidence": evidence[key],
                       "reason": "existing_value" if state == "preserved" else
                       blocked.get(key) or ("conflicting_evidence" if len(found) > 1 else
                       "saved_evidence" if value else "unverified_capture_date"
                       if key == "season" and saved.get("value") and not trusted_saved else
                       "insufficient_evidence"),
                       "clock_evidence": ({k: v.isoformat() if v else None
                                           for k, v in clocks.items()}
                                          if key == "time_of_day" else {})}
    return result, states


def correction_inputs(session, references):
    """成功runの保存計画から属性単位の所有権と最初の値を復元する。"""
    references = sorted(map(str, references))
    runs = session.scalars(select(ProcessingRun).where(
        ProcessingRun.stage == "subject", ProcessingRun.finished_at.is_not(None),
        ProcessingRun.failure_reason.is_(None),
        ProcessingRun.parameters["method"].astext == METHOD,
    ).order_by(ProcessingRun.started_at, ProcessingRun.id)).all()
    originals = [r for r in runs if str(r.id) in references]
    if sorted(str(r.id) for r in originals) != references:
        raise ValueError("訂正対象の成功runがありません")
    allowed = [r for r in runs if str(r.id) in references
               or r.parameters.get("correction_of") == references]
    saved, owned = {}, defaultdict(dict)
    for run in allowed:
        data = json.loads(Path(run.output_paths["snapshot"]).read_text(encoding="utf-8"))
        if (data["run_id"] != str(run.id) or data["dry_run"]
                or {k: v for k, v in data.items() if k != "assets"} != run.parameters):
            raise ValueError("訂正元snapshotが成功runと一致しません")
        saved[str(run.id)] = {row["asset_id"]: row for row in data["assets"]}
        if str(run.id) in references:
            for row in data["assets"]:
                for key in row["after"]:
                    if row["before"].get(key) != row["after"][key]:
                        owned[row["asset_id"]].setdefault(key, row["before"])
    return saved, owned


def execute(engine, rules, snapshot, *, code_version, dry_run=True, expected_hash=None,
            image_evidence=None, correction_runs=()):
    """#72/#99の判定で未確定だけを再評価し、属性と根拠を1取引で追記する。

    rulesは保存済みカタログを含むものを渡す。dry_runはREAD ONLY。
    image_evidenceは実画像のSHAを検証済みの、SHA→EXIF属性の保存台帳。
    指定しない場合はassetのstorage_pathを読む。
    本反映は保存した計画hashとの一致を必須とし、既存確定値を変更しない。
    correction_runsは自身の成功runのID列。属性単位の所有権を確認し、そのrunが
    書いた値だけを全根拠で再評価する。他runの値とそれ以前の確定値は更新しない。
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
        if correction_runs:
            saved, owned = correction_inputs(session, correction_runs)
            rows = [{"asset_id": str(a.id),
                     "subject_id": str(a.subject_id) if a.subject_id else None,
                     "scene_attributes": {}, "scene_evidence": {},
                     "reasons": ["existing_assignment"], "candidates": {}} for a in assets]
            catalog = {}
        else:
            rows, catalog = infer(assets, subjects, duplicates, previous, rules,
                                  verified_runs={str(r.id): r.config_hash for r in runs},
                                  verified_keys=keys)
        by_id = {str(a.id): a for a in assets}
        plan = []
        for row in rows:
            asset = by_id[row["asset_id"]]
            exif = (image_evidence.get(asset.sha256, {}) if image_evidence is not None
                    else exif_evidence(asset.storage_path))
            mutable, protected = set(), []
            evaluation = asset
            if correction_runs:
                owner = asset.quality.get("scene_inference", {}).get("run_id")
                prior = saved.get(owner, {}).get(str(asset.id), {})
                baseline = dict(asset.scene_attributes)
                for key, original in owned[str(asset.id)].items():
                    if not prior or asset.scene_attributes.get(key) != prior["after"].get(key):
                        protected.append(key)
                        continue
                    mutable.add(key)
                    if key in original:
                        baseline[key] = original[key]
                    else:
                        baseline.pop(key, None)
                evaluation = SimpleNamespace(scene_attributes=baseline, quality=asset.quality,
                                             collected_title=asset.collected_title,
                                             collected_location=asset.collected_location)
                categorical, category_states = category_scene(
                    evaluation, {"input": metadata(evaluation), "subject_id": None}, rules, {})
                row["scene_attributes"], row["scene_evidence"] = categorical, category_states
            attrs, states = scene_attributes(evaluation, rules, exif, mutable=mutable)
            # 既存のカテゴリ導出も利用するが、根拠が矛盾する撮影時属性は採用しない。
            for key, value in row["scene_attributes"].items():
                if (key not in states and attrs.get(key) in UNKNOWN
                        and not nonphotographic(evaluation)):
                    attrs[key] = value
                    states[key] = row["scene_evidence"][key]
            if correction_runs:
                recalculated = dict(asset.scene_attributes)
                for key in mutable:
                    if nonphotographic(evaluation):
                        attrs.pop(key, None)
                        states[key] = {"state": "unknown", "value": None,
                                       "reason": "nonphotographic_content", "evidence": []}
                    if key in attrs:
                        recalculated[key] = attrs[key]
                    else:
                        recalculated.pop(key, None)
                    if key not in states:
                        states[key] = {"state": "unknown", "value": None,
                                       "reason": "insufficient_evidence", "evidence": []}
                attrs = recalculated
                for key in states.keys() - mutable:
                    value = asset.scene_attributes.get(key)
                    states[key] = {"state": "preserved" if value not in UNKNOWN else "unknown",
                                   "value": value, "reason": "not_owned_by_run", "evidence": []}
            sid = str(asset.subject_id) if asset.subject_id else row["subject_id"]
            plan.append({"asset_id": str(asset.id), "before_subject": str(asset.subject_id)
                         if asset.subject_id else None, "subject_id": sid,
                         "before": asset.scene_attributes, "after": attrs,
                         "attributes": states, "identity_reasons": row["reasons"],
                         "owned_attributes": sorted(mutable), "protected_attributes": protected,
                         "identity_evidence": row["candidates"] if not asset.subject_id else {}})
        plan_hash = digest(plan)
        if not dry_run and expected_hash != plan_hash:
            raise ValueError("補完計画が事前確認と一致しません")
        changed = [r for r in plan if r["before"] != r["after"]
                   or r["before_subject"] != r["subject_id"]]
        result = {"method": METHOD, "run_id": str(run_id), "dry_run": dry_run,
                  "config_hash": digest(rules), "code_version": code_version,
                  "image_evidence_hash": digest(image_evidence),
                  "correction_of": sorted(map(str, correction_runs)),
                  "subject_keys": [{"subject_id": str(sid), "domain": target["domain"],
                                    "key": target["key"],
                                    **({"wikidata_id": target["wikidata_id"]}
                                       if target.get("wikidata_id") else {})}
                                   for sid, target in catalog.items()],
                  "plan_hash": plan_hash, "changes": len(changed),
                  "confirmed_images": sum(r["before_subject"] != r["subject_id"] for r in plan),
                  "attribute_changes": dict(Counter(
                      key for r in plan for key in r["after"].keys() | r["before"].keys()
                      if r["after"].get(key) != r["before"].get(key))),
                  "withdrawn_attributes": dict(Counter(
                      key for r in plan for key in r["before"]
                      if r["before"][key] not in UNKNOWN and r["after"].get(key) in UNKNOWN)),
                  "correction_reasons": dict(Counter(
                      r["attributes"][key].get("reason", "category_evidence")
                      for r in changed for key in r["owned_attributes"]
                      if r["before"].get(key) != r["after"].get(key))),
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
                    "owned_attributes": row["owned_attributes"],
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
