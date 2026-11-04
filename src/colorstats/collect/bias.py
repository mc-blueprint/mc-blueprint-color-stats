"""偏り制御専用ハンドラー。原本取得前の予約と結果確定を結び付ける。"""

import hashlib
import json
import os
import random
import re
import uuid
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, delete, func, or_, select, text

from colorstats.collect import SearchRequest, stage
from colorstats.collect.coverage import images, matches
from colorstats.collect.http import MeasurementLimit
from colorstats.collect.policy import load_policy
from colorstats.collect.targets import requests
from colorstats.queue import LeaseLost, Queue, RunInfo
from colorstats.queue.worker import Prepared
from colorstats.schema.models import (
    Asset,
    CollectionReservation,
    Job,
    ProcessingRun,
    Source,
    Subject,
)

# 実際に参照する予約テーブルを識別し、search_pathの違いでも排他を共有する。
LOCK_SQL = text("SELECT pg_advisory_xact_lock('collection_reservation'::regclass::oid::bigint)")


def reap(session):
    """無効な未確定予約を回収する。完了・更新中のjob行は次回へ回す。"""
    stale = (
        select(CollectionReservation.id)
        .where(
            CollectionReservation.job_id == Job.id,
            CollectionReservation.asset_id.is_(None),
            or_(
                Job.status != "running",
                Job.lease_token != CollectionReservation.lease_token,
                Job.lease_until <= func.clock_timestamp(),
            ),
        )
        .exists()
    )
    jobs = session.scalars(select(Job).where(stale).with_for_update(skip_locked=True)).all()
    for job in jobs:
        session.execute(
            delete(CollectionReservation).where(
                CollectionReservation.job_id == job.id,
                CollectionReservation.asset_id.is_(None),
                or_(
                    job.status != "running",
                    CollectionReservation.lease_token != job.lease_token,
                    job.lease_until <= func.clock_timestamp() if job.lease_until else True,
                ),
            )
        )


def pending(session) -> list[dict]:
    return [
        {
            "subject_id": reservation.subject_id,
            "author": reservation.author,
            "source": reservation.source,
            "region": reservation.region,
            "attributes": reservation.attributes,
        }
        for reservation in session.scalars(
            select(CollectionReservation)
            .where(CollectionReservation.asset_id.is_(None))
        )
    ]


def resolve_subject(session, candidate, layer, aliases):
    """登録済みsubjectの名称・別名がタイトル内で一意に一致した候補だけを扱う。

    別名は設定のsubject_aliases。空属性の旧prep生成行は同定根拠にしない。
    一致しない候補も収集対象にできる。
    """
    found = []
    for subject in session.scalars(
        select(Subject).where(Subject.domain == layer["attributes"]["domain"])
    ):
        if not subject.scene_attributes:
            continue
        names = [subject.name, *aliases.get(subject.name, [])]
        if any(
            name
            and re.search(
                rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", candidate.title, re.IGNORECASE
            )
            for name in names
        ):
            found.append(subject)
    if len(found) == 1:
        return found[0]
    return None


def reserve(queue: Queue, claim, config: dict, request, candidate) -> str | None:
    """短い直列化取引で採否を決め、採用時だけリース付きの枠を確保する。"""
    layer = next((s for s in config["strata"] if s["id"] == request.stratum), None)
    if layer is None:
        return "unknown_stratum"
    with queue._transaction() as session:
        queue._owned(session, claim)
        incompatible = session.scalar(
            select(Job.id)
            .where(
                Job.stage == "collect",
                Job.status.in_(["pending", "running"]),
                Job.payload.has_key("bias"),
                Job.payload["bias"] != config,
            )
            .limit(1)
        )
        if incompatible:
            raise ValueError("異なる偏り設定のジョブが稼働中です")
        session.execute(LOCK_SQL)
        reap(session)
        # ロック待ち中の期限切れも拒否する。
        queue._owned(session, claim)
        if "measurement" in config:
            if session.scalar(
                select(Asset.id).join(Source, Source.id == Asset.source_id).where(
                    or_(Source.url == candidate.source_url, Asset.url == candidate.original_url)
                ).limit(1)
            ):
                return "rediscovered_url"
            if session.scalar(select(CollectionReservation.id).where(
                or_(CollectionReservation.source_url == candidate.source_url,
                    CollectionReservation.attributes["_original_url"].astext
                    == candidate.original_url)
            ).limit(1)):
                return "reserved_url"
        subject = resolve_subject(session, candidate, layer, config["subject_aliases"])
        author = (candidate.author or "").strip().casefold()
        subject_id = subject.id if subject else None
        if subject and subject.location and subject.location.strip():
            region, region_basis = subject.location.strip(), "subject.location"
        elif candidate.location and candidate.location.strip():
            region, region_basis = candidate.location.strip(), "candidate.location"
        elif layer["attributes"].get("region"):
            region, region_basis = layer["attributes"]["region"], "stratum.region"
        else:
            region, region_basis = None, "unknown"
        existing = session.scalar(
            select(CollectionReservation).where(
                CollectionReservation.job_id == claim.id,
                CollectionReservation.lease_token == claim.token,
                CollectionReservation.source_url == candidate.source_url,
            )
        )
        if existing:
            return "duplicate_candidate"
        rows = images(session) + pending(session)
        layer_subjects = {
            r["subject_id"] for r in rows if r["subject_id"] and matches(r["attributes"], layer)
        }
        if len(layer_subjects) >= layer["subjects"]:
            return "target_reached"
        if "images" in layer and sum(
            matches(r["attributes"], layer) for r in rows
        ) >= layer["images"]:
            return "image_target_reached"
        reason = quota_reason(rows, config, subject_id, author, request.provider, region, layer)
        if reason:
            return reason
        session.add(
            CollectionReservation(
                job_id=claim.id,
                lease_token=claim.token,
                stratum=layer["id"],
                subject_id=subject_id,
                author=author,
                source=request.provider,
                region=region,
                region_basis=region_basis,
                attributes={**layer["attributes"], "_original_url": candidate.original_url}
                if "measurement" in config else layer["attributes"],
                source_url=candidate.source_url,
            )
        )
    return None


def quota_reason(rows, config, subject_id, author, source, region, layer):
    """全体予算と層目標の集中枠を検査する。端数は切り捨てる。"""
    budget, limits = config["image_budget"], config["limits"]
    if len(rows) >= budget:
        return "image_budget"
    for key, value in (
        ("subject_id", subject_id),
        ("author", author),
        ("source", source),
        ("region", region),
    ):
        if key != "source" and not value:
            continue
        limit_key = "subject" if key == "subject_id" else key
        cap = int(Decimal(str(limits[f"{limit_key}_share"])) * budget)
        if key == "subject_id":
            cap = min(cap, limits["subject_images"])
        if sum(row[key] == value for row in rows) >= cap:
            return f"{limit_key}_limit"
        if key in ("author", "source"):
            layer_cap = int(
                Decimal(str(limits[f"{key}_share"])) * layer.get("images", layer["subjects"])
            )
            if sum(
                row[key] == value and matches(row["attributes"], layer) for row in rows
            ) >= min(cap, layer_cap):
                return f"stratum_{key}_limit"
    return None


def plan(
    queue: Queue,
    config: dict,
    *,
    policy_path: Path,
    storage_config: Path,
    host: str,
    code_version: str,
    seed: int = 0,
) -> list[uuid.UUID]:
    """不足率の大きい層から検索を投入する。同じseed・条件ではジョブを重複させない。

    images指定時は予約を含む画像不足率、それ以外はsubject不足率を使う。
    投入後に満了した層はprepareのdecideで止める。
    seedを変えると別のオフセットを探索できる。検索の終端・次offsetはrunに記録される。
    """
    with queue._transaction() as session:
        session.execute(LOCK_SQL)
        if "measurement" in config and session.scalar(select(Job.id).where(
            Job.stage == "collect", Job.status.in_(["pending", "running"]),
            Job.payload.has_key("bias"), Job.payload["bias"] != config,
        ).limit(1)):
            raise ValueError("異なる偏り設定のジョブが稼働中です")
        reap(session)
        rows = images(session) + pending(session)
        completed = session.execute(
            select(Job.payload, ProcessingRun.parameters)
            .join(ProcessingRun, ProcessingRun.id == Job.run_id)
            .where(Job.stage == "collect", Job.payload["bias"] == config)
        ).all()
    if len(rows) >= config["image_budget"]:
        return []
    policies = {}
    for provider in config["search"]["providers"]:
        policies[provider] = load_policy(policy_path, provider)
        stage.adapter_for(provider, policies[provider])
    rng = random.Random(seed)
    layers = []
    for layer in config["strata"]:
        if "images" in layer:
            count = sum(matches(r["attributes"], layer) for r in rows)
            if count < layer["images"]:
                layers.append(((layer["images"] - count) / layer["images"], layer))
            continue
        count = len(
            {r["subject_id"] for r in rows if r["subject_id"] and matches(r["attributes"], layer)}
        )
        if count < layer["subjects"]:
            layers.append(((layer["subjects"] - count) / layer["subjects"], layer))
    job_ids = []
    for _, layer in sorted(layers, key=lambda pair: -pair[0]):
        searches = list(requests(config, layer, rng))
        if "measurement" in config:
            searches = [request for request in searches if request.page == 0]
        for previous, parameters in completed:
            offset = parameters.get("next_offset")
            previous_request = SearchRequest(**previous["request"])
            if (
                previous_request.stratum == layer["id"]
                and previous.get("seed") == seed
                and previous["code_version"] == code_version
                and previous["storage_config"] == str(storage_config.resolve())
                and previous["host"] == host
                and offset is not None
                and 0 <= offset <= config["search"]["max_offset"]
                and previous_request.page + 1 < config["search"]["pages"]
            ):
                searches.append(
                    replace(previous_request, page=previous_request.page + 1, offset=offset)
                )
        for request in searches:
            policy = policies[request.provider]
            payload = {
                "request": asdict(request),
                "policy": policy,
                "storage_config": str(storage_config.resolve()),
                "storage_hash": hashlib.sha256(storage_config.read_bytes()).hexdigest(),
                "host": host,
                "domain": layer["attributes"]["domain"],
                "code_version": code_version,
                "taxonomy_version": config["taxonomy_version"],
                "bias": config,
                "seed": seed,
            }
            digest = hashlib.sha256(
                json.dumps(
                    payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                ).encode()
            ).hexdigest()
            job_ids.append(queue.enqueue("collect", None, digest, payload))
    return job_ids


def release(queue: Queue, claim, candidate):
    """原本取得から除外された候補の、この試行が所有する未確定予約だけを解放する。"""
    with queue._transaction() as session:
        queue._owned(session, claim)
        session.execute(LOCK_SQL)
        session.execute(
            delete(CollectionReservation).where(
                CollectionReservation.job_id == claim.id,
                CollectionReservation.lease_token == claim.token,
                CollectionReservation.source_url == candidate.source_url,
                CollectionReservation.asset_id.is_(None),
            )
        )


def prepare(claim):
    """専用の採否関数を共有prepareに渡す。例外時はこの試行の未確定枠を解放する。"""
    engine = create_engine(os.environ["DATABASE_URL"])
    queue = Queue(engine)
    meter = None
    try:
        if "measurement" in claim.payload["bias"]:
            from colorstats.collect.measurement import Meter

            meter = Meter(queue, claim)
            with queue._transaction() as session:
                session.execute(LOCK_SQL)
                reap(session)
                config = claim.payload["bias"]
                layer = next(s for s in config["strata"] if s["id"] == meter.stratum)
                rows = images(session) + pending(session)
                subjects = {
                    row["subject_id"] for row in rows
                    if row["subject_id"] and matches(row["attributes"], layer)
                }
                if len(subjects) >= layer["subjects"]:
                    raise MeasurementLimit("target_reached")
                if "images" in layer and sum(
                    matches(row["attributes"], layer) for row in rows
                ) >= layer["images"]:
                    raise MeasurementLimit("image_target_reached")
                reason = quota_reason(
                    rows, config, None, "", claim.payload["request"]["provider"], None, layer
                )
                if reason:
                    raise MeasurementLimit(reason)
        prepared = stage.prepare(
            claim,
            decide=lambda request, candidate: reserve(
                queue, claim, claim.payload["bias"], request, candidate
            ),
            discard=lambda request, candidate: release(queue, claim, candidate),
            observer=meter.observe if meter else None,
        )
        prepared.data["claim_id"] = str(claim.id)
        prepared.data["claim_token"] = str(claim.token)
        if meter:
            meter.finish("prepared", parameters={"search": prepared.info.parameters})
            prepared.data["measurement_run_id"] = str(meter.id)
        return prepared
    except BaseException as error:
        with queue._transaction() as session:
            session.execute(
                delete(CollectionReservation).where(
                    CollectionReservation.job_id == claim.id,
                    CollectionReservation.lease_token == claim.token,
                    CollectionReservation.asset_id.is_(None),
                )
            )
        if meter:
            meter.finish(
                "stopped" if isinstance(error, MeasurementLimit) else "failed", error=error
            )
            if isinstance(error, MeasurementLimit):
                payload = claim.payload
                parameters = {
                    "request": payload["request"], "effective": {}, "next_offset": None,
                    "skipped": [], "stop_reason": str(error),
                }
                return Prepared(
                    RunInfo("open", payload["code_version"], payload["taxonomy_version"],
                            payload["host"], parameters),
                    {"records": [], "payload": payload, "claim_id": str(claim.id),
                     "claim_token": str(claim.token), "measurement_run_id": str(meter.id)}, [],
                )
        raise
    finally:
        engine.dispose()


def register(session, run, data):
    """共有登録後、予約と画像・subjectを同じ完了取引で確定する。"""
    session.execute(LOCK_SQL)
    measured = "measurement_run_id" in data
    known = set(session.scalars(select(Asset.sha256))) if measured else set()
    reservations = session.scalars(
        select(CollectionReservation).where(
            CollectionReservation.job_id == uuid.UUID(data["claim_id"]),
            CollectionReservation.lease_token == uuid.UUID(data["claim_token"]),
            CollectionReservation.asset_id.is_(None),
        )
    ).all()
    by_url = {reservation.source_url: reservation for reservation in reservations}
    if len(by_url) != len(data["records"]):
        raise LeaseLost("原本に対応する収集予約がありません")
    stage.register(session, run, data)
    for record, asset_id in zip(data["records"], run.parameters["asset_ids"], strict=True):
        reservation = by_url[record["candidate"]["source_url"]]
        asset = session.get(Asset, uuid.UUID(asset_id))
        asset.subject_id = reservation.subject_id
        asset.search_parameters = {
            **asset.search_parameters,
            "collection_bias": {
                "stratum": reservation.stratum,
                "intended_attributes": {
                    k: v for k, v in reservation.attributes.items() if k != "_original_url"
                },
                "region": reservation.region,
                "region_basis": reservation.region_basis,
            },
        }
        reservation.asset_id = asset.id
    if measured:
        from colorstats.collect.measurement import record

        record(session, run, data, known)
