"""独立接続で共有枠の競合・失効・送信前障害を確認する。"""

import multiprocessing
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, timedelta
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from colorstats.collect.http import HttpClient, MeasurementLimit
from colorstats.collect.limits import ProviderLease, SharedLimits, locked
from colorstats.queue import LeaseLost, Queue
from colorstats.queue.core import NonRetryableError
from colorstats.queue.worker import Worker
from tests.test_collect import Clock, Response
from tests.test_collect import policy as policy
from tests.test_queue import database as database
from tests.test_queue import expire
from tests.test_queue import queue as queue

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="PostgreSQL専用")


def enqueue(queue, provider, number):
    queue.enqueue("collect", None, f"{number:064x}", {"request": {"provider": provider}})


def claim_process(url, provider, output):
    engine = create_engine(url)
    try:
        claim = Queue(engine).claim(["collect"], provider=provider)
        output.put(claim.payload["request"]["provider"])
    finally:
        engine.dispose()


def lease_process(url, output):
    engine = create_engine(url)
    ProviderLease(Queue(engine), "openverse").acquire()
    output.put("acquired")
    while True:
        from time import sleep

        sleep(1)


def request_process(url, claim, policy, output):
    engine = create_engine(url)
    sent, waits = [], []

    def opener(*args, **kwargs):
        sent.append(True)
        return Response(b"ok")

    def wait(delay):
        waits.append(delay)
        raise MeasurementLimit("fixture_wait")

    try:
        client = HttpClient(policy, opener=opener, wait=wait)
        client.shared_limits = SharedLimits(Queue(engine), claim)
        try:
            client.get("https://upload.wikimedia.org/file", read=lambda r: r.read())
        except MeasurementLimit:
            pass
        output.put((sent, waits))
    finally:
        engine.dispose()


def test_独立processはSQLでproviderを限定し未指定callerは従来どおり(queue):
    for number, provider in enumerate(("openverse", "wikimedia_commons", "loc")):
        enqueue(queue, provider, number)
    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    url = queue.engine.url.render_as_string(hide_password=False)
    processes = [context.Process(target=claim_process, args=(url, provider, output))
                 for provider in ("wikimedia_commons", "openverse")]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(15)
            assert process.exitcode == 0
        assert {output.get(timeout=1) for _ in processes} == {"wikimedia_commons", "openverse"}
        assert queue.claim(["collect"]).payload["request"]["provider"] == "loc"
    finally:
        for process in processes:
            if process.is_alive():
                process.kill()
                process.join()
            process.close()
        output.close()
        output.join_thread()


def test_provider二重起動と期限切れの旧所有者を拒否する(queue):
    first = ProviderLease(queue, "openverse")
    second = ProviderLease(queue, "openverse")
    first.acquire()
    with pytest.raises(LeaseLost):
        second.acquire()
    with locked(queue, first.key) as (_, state, now):
        state["until"] = now - 1
    second.acquire()
    with pytest.raises(LeaseLost):
        first.renew()
    first.release()
    second.renew()
    second.release()


def test_同hostの同時枠とbyte予約を競合しても合算する(queue):
    limits = []
    for number, provider in enumerate(("openverse", "wikimedia_commons")):
        enqueue(queue, provider, number)
        limits.append(SharedLimits(queue, queue.claim(["collect"], provider=provider)))
    host_policy = {"max_concurrency": 2}
    for limiter in limits:
        assert limiter.reserve("upload.wikimedia.org", "media", host_policy, 0, []) == 0
    with ThreadPoolExecutor(2) as pool:
        chunks = list(pool.map(lambda limiter: limiter.chunk(
            "upload.wikimedia.org", 20_000_000, 31_250_000), limits))
    assert sum(size for size, _ in chunks) == 25_000_000
    third = SharedLimits(queue, limits[0].claim)
    assert third.reserve("upload.wikimedia.org", "media", host_policy, 0, []) > 0
    limits[0].finish("upload.wikimedia.org", 0, 5)
    assert third.reserve("upload.wikimedia.org", "media", host_policy, 0, []) > 0
    with locked(queue, "host:upload.wikimedia.org") as (_, state, now):
        state["cooldown"] = now - 1
        state["next"] = now - 1
    assert third.reserve("upload.wikimedia.org", "media", host_policy, 0, []) == 0
    assert third.chunk("upload.wikimedia.org", 100, 31_250_000)[0] == 0


def test_強制終了相当の未完了byteはリース失効後も窓内で保全する(queue):
    enqueue(queue, "openverse", 1)
    claim = queue.claim(["collect"])
    limiter = SharedLimits(queue, claim)
    assert limiter.reserve("media.test", "media", {}, 0, []) == 0
    assert limiter.chunk("media.test", 100, 100) == (100, 0)
    with locked(queue, "host:media.test") as (_, state, now):
        state["slots"][0]["until"] = now - 1
    with pytest.raises(LeaseLost):
        limiter.chunk("media.test", 1, 100)
    successor = SharedLimits(queue, claim)
    with pytest.raises(NonRetryableError, match="未完了"):
        successor.reserve("media.test", "media", {}, 0, [])
    with locked(queue, "host:media.test") as (_, state, now):
        assert sum(c["bytes"] for c in state["chunks"] if c["until"] > now) == 100
    expire(queue, claim)
    with pytest.raises(LeaseLost):
        limiter.chunk("media.test", 1, 100)


def test_API予約と失敗後cooldownは別接続へ残る(queue):
    enqueue(queue, "openverse", 1)
    claim = queue.claim(["collect"])
    limiter = SharedLimits(queue, claim)
    windows = [{"seconds": 60, "limit": 1}]
    assert limiter.reserve("api.test", "api", {}, 0, windows) == 0
    limiter.finish("api.test", 0)
    successor = SharedLimits(queue, claim)
    assert successor.reserve("api.test", "api", {}, 0, windows) > 0


def test_DB障害ではopenerを呼ばない(queue, policy):
    enqueue(queue, "wikimedia_commons", 1)
    limiter = SharedLimits(queue, queue.claim(["collect"]))
    opener = Mock()
    client = HttpClient(policy, opener=opener)
    client.shared_limits = limiter
    queue._transaction = Mock(side_effect=OperationalError("offline", {}, None))
    with pytest.raises(OperationalError):
        client.get("https://commons.wikimedia.org/w/api.php")
    opener.assert_not_called()


def test_別hostではprovider_workerが通信もclaimもしない(queue, tmp_path, monkeypatch):
    monkeypatch.setattr("colorstats.queue.worker.socket.gethostname", lambda: "ubuntu-2")
    worker = Worker(queue, {"collect": "colorstats.collect.stage"}, tmp_path / "stop",
                    provider="openverse")
    with pytest.raises(ValueError, match="ubuntu-1"):
        worker.run(once=True)


def test_provider期限切れにDB時刻を使う(queue):
    queue.lease = timedelta(seconds=10)
    lease = ProviderLease(queue, "openverse")
    lease.acquire()
    with queue.engine.begin() as connection:
        connection.execute(text(
            "UPDATE collection_limit SET state=jsonb_set(state,'{until}','0')"
        ))
    with pytest.raises(LeaseLost):
        lease.renew()


def test_provider所有processの強制終了後も期限まで二重起動しない(queue):
    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    process = context.Process(target=lease_process, args=(
        queue.engine.url.render_as_string(hide_password=False), output,
    ))
    process.start()
    try:
        assert output.get(timeout=15) == "acquired"
        process.kill()
        process.join(5)
        assert not process.is_alive()
        lease = ProviderLease(queue, "openverse")
        with pytest.raises(LeaseLost):
            lease.acquire()
        with locked(queue, lease.key) as (_, state, now):
            state["until"] = now - 1
        lease.acquire()
        lease.release()
    finally:
        if process.is_alive():
            process.kill()
            process.join()
        process.close()
        output.close()
        output.join_thread()


def test_fake_clockとstreamで共有窓とnetwork中の取引解放を確認する(queue, policy, monkeypatch):
    from colorstats.collect import limits

    clock = Clock()
    original = limits.locked
    with queue.engine.connect() as connection:
        epoch = connection.scalar(text("SELECT extract(epoch FROM clock_timestamp())"))

    @contextmanager
    def timed(*args):
        with original(*args) as (session, state, _):
            yield session, state, float(epoch) + clock.now

    monkeypatch.setattr(limits, "locked", timed)
    reads = []

    class Stream(Response):
        def read1(self, size):
            with queue.engine.connect() as connection:
                assert connection.scalar(text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname=current_database() AND state='idle in transaction'"
                )) == 0
            data = super().read1(size)
            reads.append((clock.now, len(data)))
            return data

    policy["hosts"]["upload.wikimedia.org"]["media_bytes_per_10_seconds"] = 10
    policy["hosts"]["upload.wikimedia.org"]["min_interval"] = 0.001
    for number, provider in enumerate(("openverse", "wikimedia_commons")):
        enqueue(queue, provider, number)
        claim = queue.claim(["collect"], provider=provider)
        client = HttpClient(policy, opener=lambda *a, **kw: Stream(b"x" * 12),
                            clock=clock.clock, wait=clock.wait)
        client.shared_limits = SharedLimits(queue, claim)
        data = client.get("https://upload.wikimedia.org/image", read=lambda r: r.read())
        assert data == b"x" * 12
    assert sum(size for _, size in reads) == 24
    for at, _ in reads:
        assert sum(size for when, size in reads if at - 10 < when <= at) <= 10


def test_JSONB復元後も最長suffixを優先しAPIとmedia共有枠を守る(queue):
    from pathlib import Path

    from colorstats.collect.policy import host_rate_group, load_policy

    policy = load_policy(Path("configs/source_policy.yaml"), "openverse")
    queue.enqueue("collect", None, "f" * 64,
                  {"request": {"provider": "openverse"}, "policy": policy})
    claim = queue.claim(["collect"])
    client = HttpClient(claim.payload["policy"])
    assert client._host_policy("https://api.openverse.org/v1/images/")["kind"] == "api"
    for host in ("upload.wikimedia.org", "thumb.wikimedia.org"):
        assert client._host_policy("https://" + host + "/image")["kind"] == "media"
        assert host_rate_group(host, claim.payload["policy"]["hosts"]) == "upload.wikimedia.org"


def test_応答後のDB障害では不明なcooldownを期限切れで解除しない(queue, policy):
    from colorstats.collect.http import _host_state

    enqueue(queue, "wikimedia_commons", 1)
    claim = queue.claim(["collect"])
    limiter = SharedLimits(queue, claim)
    client = HttpClient(policy, opener=lambda *a, **kw: Response({}))
    client.shared_limits = limiter

    def observer(event, value):
        if event in ("responses", "network_api_seconds"):
            raise OperationalError("offline", {}, None)

    client.observer = observer
    with pytest.raises(OperationalError):
        client.get("https://commons.wikimedia.org/w/api.php")
    semaphore = _host_state("commons.wikimedia.org")["semaphore"]
    assert semaphore.acquire(blocking=False)
    semaphore.release()
    with locked(queue, "host:commons.wikimedia.org") as (_, state, now):
        assert len(state["slots"]) == 1
        state["slots"][0]["until"] = now - 1
    with pytest.raises(NonRetryableError, match="未完了"):
        SharedLimits(queue, claim).reserve("commons.wikimedia.org", "api", {}, 0, [])


@pytest.mark.parametrize("status", [429, 503])
def test_RetryAfterを本文受信中に別workerへ共有する(queue, policy, status):
    for number, provider in enumerate(("wikimedia_commons", "openverse")):
        enqueue(queue, provider, number)
    first = queue.claim(["collect"], provider="wikimedia_commons")
    second = queue.claim(["collect"], provider="openverse")
    body_started, release = threading.Event(), threading.Event()

    class Body(Response):
        def read1(self, size):
            body_started.set()
            assert release.wait(15)
            return super().read1(size)

    policy["retries"] = 0
    policy["hosts"]["upload.wikimedia.org"]["min_interval"] = 0.001

    def opener(*args, **kwargs):
        raise HTTPError("https://upload.wikimedia.org/file", status, "busy",
                        {"Retry-After": "30"}, Body(b"busy"))

    client = HttpClient(policy, opener=opener, wait=lambda _: None)
    client.shared_limits = SharedLimits(queue, first)
    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    process = context.Process(target=request_process, args=(
        queue.engine.url.render_as_string(hide_password=False), second, policy, output,
    ))
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(client.get, "https://upload.wikimedia.org/file")
        try:
            assert body_started.wait(10)
            process.start()
            process.join(10)
            assert process.exitcode == 0
            sent, waits = output.get(timeout=1)
            assert not sent and waits
            with locked(queue, "host:upload.wikimedia.org") as (_, state, now):
                assert len(state["slots"]) == 1
                assert state["concurrency"] == 2 and state["cooldown"] > now + 15
        finally:
            release.set()
            if process.pid is not None:
                if process.is_alive():
                    process.kill()
                    process.join()
                process.close()
            output.close()
            output.join_thread()
        with pytest.raises(RuntimeError, match="負荷制限"):
            future.result(timeout=5)


def test_匿名5回毎時の初回は共有待機を消費せず3600秒待たない(queue, monkeypatch):
    from pathlib import Path

    from colorstats.collect import limits
    from colorstats.collect.http import _host_state
    from colorstats.collect.policy import load_policy

    policy = load_policy(Path("configs/source_policy.yaml"), "openverse")
    enqueue(queue, "openverse", 1)
    claim = queue.claim(["collect"])
    with locked(queue, "host:api.openverse.org") as (_, state, epoch):
        state.update(slots=[], events=[], chunks=[], cooldown=epoch + 5)
    clock = Clock()
    original = limits.locked

    @contextmanager
    def timed(*args):
        with original(*args) as (session, state, _):
            yield session, state, epoch + clock.now

    monkeypatch.setattr(limits, "locked", timed)
    sends = []

    def opener(*args, **kwargs):
        sends.append(clock.now)
        return Response({})

    client = HttpClient(policy, opener=opener, clock=clock.clock, wait=clock.wait)
    client.shared_limits = SharedLimits(queue, claim)
    assert client.get("https://api.openverse.org/v1/images/") == {}
    assert len(sends) == 1 and 5 <= sends[0] < 10
    assert list(_host_state("api.openverse.org")["api_requests"]) == sends
    with locked(queue, "host:api.openverse.org") as (_, state, _):
        assert len(state["events"]) == 1


def test_0008の非空台帳はdowngradeを拒否して台帳とrevisionを保全する(queue, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.exc import DBAPIError

    monkeypatch.setenv("DATABASE_URL", queue.engine.url.render_as_string(hide_password=False))
    lease = ProviderLease(queue, "openverse")
    lease.acquire()
    with queue.engine.connect() as connection:
        before = connection.execute(text("SELECT key, state FROM collection_limit")).all()
    with pytest.raises(DBAPIError, match="通信枠台帳が残る"):
        command.downgrade(Config("alembic.ini"), "0007")
    with queue.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0008"
        assert connection.execute(text("SELECT key, state FROM collection_limit")).all() == before


def test_HTTP日時のRetryAfterもworker時計ではなくDB時計と比較する(queue, policy, monkeypatch):
    from email.utils import format_datetime

    enqueue(queue, "wikimedia_commons", 1)
    limiter = SharedLimits(queue, queue.claim(["collect"]))
    assert limiter.reserve("upload.wikimedia.org", "media", {}, 0, []) == 0
    with queue.engine.connect() as connection:
        due = connection.scalar(text("SELECT clock_timestamp()")) + timedelta(seconds=60)
    client = HttpClient(policy)
    client.shared_limits = limiter
    worker_clock = Mock()
    monkeypatch.setattr("colorstats.collect.http.datetime", worker_clock)
    client._delay({"Retry-After": format_datetime(due.astimezone(UTC), usegmt=True)}, 0,
                  "https://upload.wikimedia.org/file")
    worker_clock.now.assert_not_called()
    with locked(queue, "host:upload.wikimedia.org") as (_, state, now):
        assert 58 < state["cooldown"] - now <= 60
