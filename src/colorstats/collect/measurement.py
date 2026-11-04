"""追加収集の試行台帳。通信枠は予約と同じDBロックで直列化する。"""

import uuid
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import func, select

from colorstats.collect.http import MeasurementLimit
from colorstats.schema.models import Asset, Job, ProcessingRun, Source
from colorstats.stats.licenses import exclusion_reasons


class Meter:
    """bias測定の試行runを作成する。observeは通信前後の短い取引で台帳を更新する。

    所有権喪失は伝播する。HTTP枠の予約は失敗・再試行でも返却しない。
    取得済みの通信記録は画像登録のrollback後も残る。
    """

    def __init__(self, queue, claim):
        from colorstats.collect.bias import LOCK_SQL

        self.queue, self.claim = queue, claim
        payload = claim.payload
        self.settings = payload["bias"]["measurement"]
        self.stratum = payload["request"]["stratum"]
        with queue._transaction() as session:
            queue._owned(session, claim)
            session.execute(LOCK_SQL)
            if session.scalar(
                select(Job.id)
                .where(
                    Job.stage == "collect",
                    Job.status.in_(["pending", "running"]),
                    Job.payload.has_key("bias"),
                    Job.payload["bias"] != payload["bias"],
                )
                .limit(1)
            ):
                raise ValueError("異なる偏り設定のジョブが稼働中です")
            previous = session.scalars(
                select(ProcessingRun).where(
                    ProcessingRun.parameters["measurement_id"].astext == self.settings["id"]
                )
            ).all()
            if any(r.parameters["bias"] != payload["bias"] for r in previous):
                raise ValueError("同じ測定IDに異なる設定を使用できません")
            if any(
                r.parameters["request"]["provider"] == payload["request"]["provider"]
                and r.parameters["policy"] != payload["policy"]
                for r in previous
            ):
                raise ValueError("測定中のsource_policyを変更できません")
            run = ProcessingRun(
                stage="collect",
                license_class="restricted",
                config_hash=claim.config_hash,
                code_version=payload["code_version"],
                taxonomy_version=payload["taxonomy_version"],
                node=payload["host"],
                started_at=claim.started_at,
                parameters={
                    "measurement_id": self.settings["id"],
                    "stratum": self.stratum,
                    "job_id": str(claim.id),
                    "attempt": claim.attempt,
                    "request": payload["request"],
                    "policy": payload["policy"],
                    "bias": payload["bias"],
                    "state": "running",
                    "counts": dict.fromkeys(
                        (
                            "requests",
                            "api_requests",
                            "responses",
                            "timeouts",
                            "bytes",
                            "search_responses",
                            "candidates",
                            "verified",
                            "downloads",
                            "download_bytes",
                            "registered",
                            "new_sha",
                            "eligible_new_sha",
                            "duplicate_sha",
                        ),
                        0,
                    ),
                    "baseline_subject_ids": (
                        previous[0].parameters["baseline_subject_ids"]
                        if previous
                        else sorted(
                            {
                                str(sid)
                                for sid in session.scalars(
                                    select(Asset.subject_id).where(
                                        Asset.subject_id.is_not(None),
                                        Asset.quality["subject_inference"]["state"].astext
                                        == "confirmed",
                                    )
                                )
                            }
                        )
                    ),
                },
            )
            session.add(run)
            session.flush()
            self.id = run.id

    def observe(self, event, value=1):
        from colorstats.collect.bias import LOCK_SQL

        with self.queue._transaction() as session:
            self.queue._owned(session, self.claim)
            session.execute(LOCK_SQL)
            run = session.get(ProcessingRun, self.id)
            counts = Counter(run.parameters["counts"])
            if event in ("search", "candidate", "exclusion"):
                search = dict(run.parameters.get("search", {}))
                if event == "search":
                    search.update(value)
                else:
                    if event == "candidate":
                        search["candidates"] = [*search.get("candidates", []), value]
                        counts["candidates"] += 1
                        counts["verified"] += int(value["verified"])
                    if value["reason"]:
                        skipped = {
                            k: value[k] for k in ("source_url", "original_url", "rank", "reason")
                        }
                        if skipped not in search.get("skipped", []):
                            search["skipped"] = [*search.get("skipped", []), skipped]
                            counts["excluded:" + value["reason"]] += 1
                run.parameters = {**run.parameters, "search": search, "counts": dict(counts)}
                return
            if event in ("api_request", "request"):
                rows = session.scalars(
                    select(ProcessingRun).where(
                        ProcessingRun.parameters["measurement_id"].astext == self.settings["id"],
                        ProcessingRun.parameters["stratum"].astext == self.stratum,
                    )
                ).all()
                totals = Counter()
                for row in rows:
                    totals.update(row.parameters["counts"])
                if totals["requests"] >= self.settings["http_requests_per_stratum"]:
                    raise MeasurementLimit("http_limit")
                if event == "api_request":
                    if totals["api_requests"] >= self.settings["api_requests_per_stratum"]:
                        raise MeasurementLimit("api_limit")
                    counts["api_requests"] += 1
                counts["requests"] += 1
                provider = self.claim.payload["request"]["provider"]
                allocation = self.settings.get("providers", {}).get(provider)
                if allocation:
                    own = Counter()
                    for row in rows:
                        if row.parameters["request"]["provider"] == provider:
                            own.update(row.parameters["counts"])
                    if own["requests"] >= allocation["http_requests"]:
                        raise MeasurementLimit("provider_http_limit")
                    if event == "api_request" and own["api_requests"] >= allocation["api_requests"]:
                        raise MeasurementLimit("provider_api_limit")
            else:
                counts[event] += value
            run.parameters = {**run.parameters, "counts": dict(counts)}

    def finish(self, state, *, parameters=None, error=None):
        with self.queue._transaction() as session:
            self.queue._owned(session, self.claim)
            run = session.get(ProcessingRun, self.id)
            run.parameters = {**run.parameters, **(parameters or {}), "state": state}
            run.failure_reason = type(error).__name__ if error else None
            run.finished_at = session.scalar(select(func.clock_timestamp()))


def record(session, run, data, known):
    """登録前のSHA集合を受け、bias.registerの完了取引内でD15分母を確定する。"""
    trial = session.get(ProcessingRun, uuid.UUID(data["measurement_run_id"]))
    counts = Counter(trial.parameters["counts"])
    reasons = Counter()
    seen, eligible = set(), set()
    for asset_id in run.parameters["asset_ids"]:
        asset = session.get(Asset, uuid.UUID(asset_id))
        source = session.get(Source, asset.source_id)
        quality = dict(asset.quality)
        origin = {
            key: getattr(source, key)
            for key in ("license", "license_class", "url", "attribution", "author", "policy")
        }
        metadata = quality.get("metadata", {})
        selected = metadata.get("openverse", {})
        name = quality.get("license")
        if (
            asset.search_provider == "openverse"
            and metadata.get("source_verified")
            and name in ("by", "by-sa")
            and selected.get("license") == name
            and source.license == name
        ):
            quality["license"] = origin["license"] = f"cc-{name}-{selected.get('license_version')}"
        excluded = exclusion_reasons(
            {"quality": quality, "license_class": asset.license_class,
             "url": asset.url, "retrieved_at": asset.retrieved_at},
            origin,
            [],
        )
        if asset.sha256 in known or asset.sha256 in seen:
            counts["duplicate_sha"] += 1
        if not excluded and asset.sha256 not in known:
            eligible.add(asset.sha256)
        seen.add(asset.sha256)
        reasons.update(excluded)
    counts["registered"] = len(run.parameters["asset_ids"])
    counts["new_sha"] = len(seen - known)
    counts["eligible_new_sha"] = len(eligible)
    trial.parameters = {
        **trial.parameters,
        "state": "committed",
        "counts": dict(counts),
        "stop_reason": run.parameters.get("stop_reason"),
        "d15_exclusions": dict(reasons),
        "collection_run_id": str(run.id),
    }
    trial.finished_at = datetime.now(UTC)
    run.parameters = {**run.parameters, "measurement_run_id": str(trial.id)}


def report(session, measurement_id):
    """試行を全件含め層別に集計する。未確定試行の通信量も分母へ含める。"""
    layers = {}
    for run in session.scalars(
        select(ProcessingRun).where(
            ProcessingRun.parameters["measurement_id"].astext == measurement_id
        )
    ):
        p = run.parameters
        layer = layers.setdefault(
            p["stratum"],
            {
                "attempts": 0,
                "states": Counter(),
                "counts": Counter(),
                "d15_exclusions": Counter(),
                "history": [],
                "asset_ids": [],
            },
        )
        layer["attempts"] += 1
        layer["states"][p["state"]] += 1
        layer["counts"].update(p["counts"])
        layer["d15_exclusions"].update(p.get("d15_exclusions", {}))
        layer["history"].append({"run_id": str(run.id), **p})
        if p["state"] == "committed":
            collection = session.get(ProcessingRun, uuid.UUID(p["collection_run_id"]))
            layer["asset_ids"].extend(collection.parameters["asset_ids"])
    for layer in layers.values():
        counts = layer["counts"]
        assets = session.scalars(
            select(Asset).where(Asset.id.in_([uuid.UUID(aid) for aid in layer.pop("asset_ids")]))
        ).all()
        subjects = {
            str(asset.subject_id)
            for asset in assets
            if asset.subject_id is not None
            and asset.quality.get("subject_inference", {}).get("state") == "confirmed"
        }
        baseline = set(layer["history"][0]["baseline_subject_ids"])
        counts["confirmed_subjects"] = len(subjects)
        counts["new_subjects"] = len(subjects - baseline)
        layer["eligible_new_sha_per_api_request"] = (
            counts["eligible_new_sha"] / counts["api_requests"] if counts["api_requests"] else None
        )
    return {"measurement_id": measurement_id, "strata": layers}
