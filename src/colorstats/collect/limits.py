"""短い行ロックでproviderの所有権と送信前の通信・byte枠を予約する。"""

import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from colorstats.collect.policy import host_rate_group
from colorstats.queue import LeaseLost
from colorstats.queue.core import NonRetryableError
from colorstats.schema.models import CollectionLimit, Job, ProcessingRun


@contextmanager
def locked(queue, key):
    with queue._transaction() as session:
        session.execute(insert(CollectionLimit).values(key=key, state={})
                        .on_conflict_do_nothing())
        row = session.scalar(select(CollectionLimit).where(CollectionLimit.key == key)
                             .with_for_update())
        now = session.scalar(select(func.clock_timestamp())).timestamp()
        state = deepcopy(row.state)
        yield session, state, now
        row.state = state


class ProviderLease:
    """同一DBのproviderを単一workerが所有する。失効・DB失敗は呼出元へ伝播する。"""

    def __init__(self, queue, provider):
        self.queue = queue
        self.key = "provider:" + provider
        self.token = str(uuid.uuid4())

    def acquire(self):
        with locked(self.queue, self.key) as (session, state, now):
            running = session.scalar(select(Job.id).where(
                Job.stage == "collect", Job.status == "running",
                Job.lease_until > func.clock_timestamp(),
                Job.payload["request"]["provider"].astext == self.key.removeprefix("provider:"),
            ).limit(1))
            if state.get("until", 0) > now or running is not None:
                raise LeaseLost("同じproviderのworkerが稼働中です")
            state.update(token=self.token, until=now + self.queue.lease.total_seconds())

    def renew(self):
        with locked(self.queue, self.key) as (_, state, now):
            if state.get("token") != self.token or state.get("until", 0) <= now:
                raise LeaseLost("providerの所有権を失いました")
            state["until"] = now + self.queue.lease.total_seconds()

    def release(self):
        with locked(self.queue, self.key) as (_, state, now):
            if state.get("token") == self.token:
                state["until"] = now


class SharedLimits:
    """各HTTPと受信チャンクの直前に予約する。DB障害時は通信を許可しない。

    未完了のbyte予約は通信リース終了後10秒まで保持し、失敗時も払い戻さない。
    HTTPのsocket timeoutは60秒、通信リースは120秒。各read前に所有権を再確認する。
    """

    def __init__(self, queue, claim):
        self.queue, self.claim = queue, claim
        self.slots = {}

    def _history(self, session, group):
        events = []
        for run in session.scalars(select(ProcessingRun).where(
            ProcessingRun.parameters.has_key("quota_events")
        )):
            hosts = run.parameters.get("policy", {}).get("hosts", {})
            for event in run.parameters["quota_events"]:
                if event.get("rate_group", host_rate_group(event["host"], hosts)) == group:
                    events.append({**event, "at": datetime.fromisoformat(event["at"]).timestamp()})
        return events

    def reserve(self, group, kind, policy, interval, windows):
        with locked(self.queue, "host:" + group) as (session, state, now):
            self.queue._owned(session, self.claim)
            if not state:
                history = self._history(session, group)
                state.update(slots=[], events=[e for e in history if e["kind"] == "api"],
                             chunks=[{"bytes": e["bytes"], "until": e["at"] + 10}
                                     for e in history if e["kind"] == "media"])
            if any(s["until"] <= now for s in state["slots"]):
                raise NonRetryableError("未完了の通信予約が失効したためhostの確認が必要です")
            concurrency = policy.get("max_concurrency", 1)
            state["concurrency"] = min(state.get("concurrency", concurrency), concurrency)
            due = max(state.get("next", 0), state.get("cooldown", 0))
            if len(state["slots"]) >= state["concurrency"]:
                due = max(due, now + 0.2)
            longest = max((w["seconds"] for w in windows), default=86400)
            state["events"] = [e for e in state["events"] if e["at"] > now - longest]
            if kind == "api":
                for window in windows:
                    times = sorted(e["at"] for e in state["events"]
                                   if e["at"] > now - window["seconds"])
                    if len(times) >= window["limit"]:
                        due = max(due, times[-window["limit"]] + window["seconds"])
            if due > now:
                return due - now
            token = str(uuid.uuid4())
            state["slots"].append({"token": token, "until": now + 120})
            state["next"] = now + interval
            if kind == "api":
                state["events"].append({"at": now, "kind": kind})
            self.slots[group] = token
        return 0.0

    def cooldown(self, group, delay, retry_at=None):
        """応答ヘッダーの停止指定を本文読取り前にDB時計で確定し、残り秒数を返す。"""
        with locked(self.queue, "host:" + group) as (session, state, now):
            self.queue._owned(session, self.claim)
            state["cooldown"] = max(state.get("cooldown", 0), now + delay, retry_at or 0)
            return state["cooldown"] - now

    def chunk(self, group, size, limit):
        with locked(self.queue, "host:" + group) as (session, state, now):
            self.queue._owned(session, self.claim)
            slot = next((s for s in state["slots"]
                         if s["token"] == self.slots[group] and s["until"] > now), None)
            if slot is None:
                raise LeaseLost("通信リースが失効しました")
            slot["until"] = now + 120
            if not limit:
                return size, 0.0
            if group == "upload.wikimedia.org":
                limit = min(limit, 25000000)
            state["byte_limit"] = min(state.get("byte_limit", limit), limit)
            state["chunks"] = [c for c in state["chunks"] if c["until"] > now]
            available = state["byte_limit"] - sum(c["bytes"] for c in state["chunks"])
            if available <= 0:
                return 0, min(c["until"] for c in state["chunks"]) - now
            size = min(size, available)
            state["chunks"].append({"bytes": size, "until": now + 130,
                                    "token": self.slots[group]})
            return size, 0.0

    def received(self, group):
        with locked(self.queue, "host:" + group) as (session, state, now):
            self.queue._owned(session, self.claim)
            for chunk in state["chunks"]:
                if chunk.get("token") == self.slots[group] and chunk["until"] > now + 10:
                    chunk["until"] = now + 10

    def finish(self, group, delay, backoff=0):
        token = self.slots.pop(group, None)
        if token is None:
            return
        with locked(self.queue, "host:" + group) as (_, state, now):
            state["slots"] = [s for s in state["slots"] if s["token"] != token]
            state["next"] = max(state.get("next", 0), now + delay)
            state["cooldown"] = max(state.get("cooldown", 0), now + backoff)
