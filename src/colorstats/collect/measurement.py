"""追加収集の試行台帳。通信枠は予約と同じDBロックで直列化する。"""

import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from time import monotonic

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
        self.started = monotonic()
        self.database_timing = {
            "lock_wait_seconds": 0.0,
            "processing_seconds": 0.0,
            "commit_seconds": 0.0,
        }
        payload = claim.payload
        self.settings = payload["bias"]["measurement"]
        self.stratum = payload["request"]["stratum"]
        with self._transaction() as session:
            queue._owned(session, claim)
            self._lock(session, LOCK_SQL)
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
                            "network_api_seconds",
                            "network_page_seconds",
                            "network_media_seconds",
                            "normal_wait_seconds",
                            "backoff_seconds",
                            "bandwidth_wait_seconds",
                        ),
                        0,
                    ),
                    "database_timing": dict(self.database_timing),
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

    @contextmanager
    def _transaction(self):
        started = monotonic()
        self._current_lock_wait = 0.0
        commit_started = None
        try:
            with self.queue._transaction() as session:
                yield session
                session.flush()
                commit_started = monotonic()
        except BaseException:
            self.database_timing["lock_wait_seconds"] += self._current_lock_wait
            self.database_timing["processing_seconds"] += max(
                0.0, monotonic() - started - self._current_lock_wait
            )
            raise
        elapsed = monotonic()
        self.database_timing["lock_wait_seconds"] += self._current_lock_wait
        self.database_timing["processing_seconds"] += max(
            0.0, commit_started - started - self._current_lock_wait
        )
        self.database_timing["commit_seconds"] += elapsed - commit_started

    def _lock(self, session, lock_sql):
        started = monotonic()
        session.execute(lock_sql)
        self._current_lock_wait += monotonic() - started

    def reserve_quota(self, host, kind, windows):
        if kind != "api":
            return 0.0
        if not windows:
            return 0.0
        from colorstats.collect.bias import LOCK_SQL

        now = datetime.now(UTC)
        delay = 0.0
        with self._transaction() as session:
            self.queue._owned(session, self.claim)
            self._lock(session, LOCK_SQL)
            rows = session.scalars(
                select(ProcessingRun).where(ProcessingRun.parameters.has_key("quota_events"))
            )
            timestamps = sorted(
                datetime.fromisoformat(event["at"])
                for row in rows
                for event in row.parameters["quota_events"]
                if event["host"] == host and event["kind"] == kind
            )
            for window in windows:
                recent = [
                    timestamp for timestamp in timestamps
                    if timestamp > now - timedelta(seconds=window["seconds"])
                ]
                if len(recent) >= window["limit"]:
                    delay = max(
                        delay,
                        (recent[-window["limit"]] + timedelta(seconds=window["seconds"]) - now)
                        .total_seconds(),
                    )
            if delay <= 0:
                run = session.get(ProcessingRun, self.id)
                events = run.parameters.get("quota_events", [])
                run.parameters = {
                    **run.parameters,
                    "quota_events": [
                        *events, {"host": host, "kind": kind, "at": now.isoformat()}
                    ],
                }
        return delay

    def media_history(self, host):
        now = datetime.now(UTC)
        hosts = self.claim.payload["policy"].get("hosts", {})
        group = hosts.get(host, {}).get("rate_group", host)
        aliases = {name for name, policy in hosts.items()
                   if policy.get("rate_group", name) == group} | {group}
        with self.queue._transaction() as session:
            rows = session.scalars(
                select(ProcessingRun).where(
                    ProcessingRun.parameters.has_key("quota_events")
                )
            )
            return [
                (max(0.0, (now - datetime.fromisoformat(event["at"])).total_seconds()),
                 event["bytes"])
                for row in rows
                for event in row.parameters["quota_events"]
                if event["host"] in aliases and event["kind"] == "media"
                and datetime.fromisoformat(event["at"]) > now - timedelta(seconds=10)
            ]

    def observe(self, event, value=1):
        from colorstats.collect.bias import LOCK_SQL

        with self._transaction() as session:
            self.queue._owned(session, self.claim)
            self._lock(session, LOCK_SQL)
            run = session.get(ProcessingRun, self.id)
            counts = Counter(run.parameters["counts"])
            database_timing = dict(run.parameters["database_timing"])
            database_timing.update(self.database_timing)
            database_timing["lock_wait_seconds"] += self._current_lock_wait
            if event == "media_transfer":
                run.parameters = {
                    **run.parameters,
                    "quota_events": [
                        *run.parameters.get("quota_events", []),
                        {"host": value["host"], "kind": "media",
                         "at": datetime.now(UTC).isoformat(), "bytes": value["bytes"]},
                    ],
                    "database_timing": database_timing,
                }
                return
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
                run.parameters = {
                    **run.parameters, "search": search, "counts": dict(counts),
                    "database_timing": database_timing,
                }
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
            run.parameters = {
                **run.parameters, "counts": dict(counts), "database_timing": database_timing,
            }

    def finish(self, state, *, parameters=None, error=None):
        from colorstats.collect.bias import LOCK_SQL

        with self._transaction() as session:
            self.queue._owned(session, self.claim)
            self._lock(session, LOCK_SQL)
            run = session.get(ProcessingRun, self.id)
            run.parameters = {**run.parameters, **(parameters or {}), "state": state}
            database_timing = dict(self.database_timing)
            database_timing["lock_wait_seconds"] += self._current_lock_wait
            run.parameters = {**run.parameters, "database_timing": database_timing}
            run.failure_reason = type(error).__name__ if error else None
            run.finished_at = session.scalar(select(func.clock_timestamp()))
        elapsed = max(0.0, monotonic() - self.started)
        with self._transaction() as session:
            self.queue._owned(session, self.claim)
            self._lock(session, LOCK_SQL)
            run = session.get(ProcessingRun, self.id)
            run.parameters = {
                **run.parameters,
                "elapsed_seconds": elapsed,
                "database_timing": dict(self.database_timing),
            }


def record(session, run, data, known):
    """登録前のSHA集合を受け、bias.registerの完了取引内でD15分母を確定する。"""
    trial = session.get(ProcessingRun, uuid.UUID(data["measurement_run_id"]))
    counts = Counter(trial.parameters["counts"])
    reasons = Counter()
    seen, eligible = set(), set()
    for record, asset_id in zip(data["records"], run.parameters["asset_ids"], strict=True):
        digest = record["sha256"]
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
        if digest in known or digest in seen:
            counts["duplicate_sha"] += 1
        if not excluded and digest not in known:
            eligible.add(digest)
        seen.add(digest)
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
