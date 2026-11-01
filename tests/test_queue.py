import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic, sleep

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from colorstats.queue import LeaseLost, Queue, RunInfo
from colorstats.queue.worker import Worker
from colorstats.schema.models import Asset, ColorObservation, Job, ProcessingRun, Source
from colorstats.store import temporary_path

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="CIのPostgreSQL専用"
)
ROOT = Path(__file__).resolve().parents[1]
INFO = RunInfo("open", "test", "0.1.0", "worker-2", {})


@pytest.fixture(scope="module")
def database():
    url = make_url(os.environ["TEST_DATABASE_URL"])
    admin = create_engine(url)
    schema = "queue_test_" + uuid.uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = url.update_query_dict({"options": f"-csearch_path={schema}"})
    engine = create_engine(url)
    config = Config(str(ROOT / "alembic.ini"))
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    try:
        command.upgrade(config, "head")
        yield engine
    finally:
        engine.dispose()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def queue(database):
    with database.begin() as connection:
        connection.execute(text("TRUNCATE job, processing_run, source, asset CASCADE"))
    return Queue(database)


@pytest.fixture
def asset(queue):
    with Session(queue.engine) as session, session.begin():
        source = Source(
            url="https://example.test/source",
            site="test",
            license="CC0",
            license_class="open",
            retrieved_at=datetime.now(UTC),
            policy={},
        )
        session.add(source)
        session.flush()
        asset = Asset(
            source_id=source.id,
            url="https://example.test/image",
            sha256="a" * 64,
            storage_path="raw/aa/" + "a" * 64 + ".png",
            domain="real_building",
            license_class="open",
            retrieved_at=datetime.now(UTC),
            taxonomy_version="0.1.0",
            scene_attributes={},
            quality={},
        )
        session.add(asset)
        session.flush()
        return asset.id


def expire(queue, claim):
    with queue.engine.begin() as connection:
        connection.execute(
            update(Job)
            .where(Job.id == claim.id)
            .values(lease_until=func.clock_timestamp() - timedelta(seconds=1))
        )


def observation(asset):
    def register(session, run):
        session.add(
            ColorObservation(
                asset_id=asset,
                processing_run_id=run.id,
                observed_oklab={"dominant": [0.5, 0, 0]},
                area_ratio=1,
            )
        )

    return register


def read_job(queue, job_id):
    with Session(queue.engine) as session:
        return session.get(Job, job_id)


def output(queue, run_id, target):
    with Session(queue.engine) as session:
        return Path(session.get(ProcessingRun, run_id).output_paths[str(target)])


def test_リース切れの他ノード引継ぎと旧ワーカーの確定を拒否する(queue, asset, tmp_path):
    job_id = queue.enqueue("color", asset, "a" * 64, {})
    old = queue.claim(["color"])
    target = tmp_path / "result"
    stale = temporary_path(target, str(old.token))
    stale.write_text("stale")
    expire(queue, old)
    other_node = Queue(queue.engine)
    current = other_node.claim(["color"])
    assert current.id == old.id and current.token != old.token and current.attempt == 2
    for operation in (
        lambda: queue.renew(old),
        lambda: queue.fail(old, "old"),
        lambda: queue.complete(old, INFO, observation(asset), [(stale, target)]),
    ):
        with pytest.raises(LeaseLost):
            operation()
    assert not target.exists()
    fresh = temporary_path(target, str(current.token))
    fresh.write_text("fresh")
    run_id = other_node.complete(current, INFO, observation(asset), [(fresh, target)])
    assert read_job(queue, job_id).run_id == run_id
    published = output(queue, run_id, target)
    assert published.read_text() == "fresh" and stale.exists()
    assert queue.complete(old, INFO, observation(asset), [(stale, target)]) == run_id
    assert published.read_text() == "fresh"
    with Session(queue.engine) as session:
        assert session.scalar(select(func.count()).select_from(ColorObservation)) == 1
        assert session.scalar(select(func.count()).select_from(ProcessingRun)) == 1


@pytest.mark.parametrize("with_asset", [True, False])
def test_並行再投入と完了後の再投入が重複しない(queue, asset, with_asset):
    target = asset if with_asset else None

    def enqueue(_):
        return queue.enqueue("color", target, "a" * 64, {})

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(enqueue, range(8)))
    assert len(set(ids)) == 1
    claim = queue.claim(["color"])
    queue.complete(claim, INFO, observation(asset))
    assert enqueue(None) == ids[0]
    assert queue.claim(["color"]) is None
    with pytest.raises(ValueError, match="payload"):
        queue.enqueue("color", target, "a" * 64, {"different": True})
    with Session(queue.engine) as session:
        assert session.scalar(select(func.count()).select_from(ColorObservation)) == 1


@pytest.mark.parametrize("lease_failure", [False, True])
def test_3回の失敗と期限切れが理由付きfailedになる(queue, lease_failure):
    job_id = queue.enqueue("prep", None, "a" * 64, {})
    for attempt in range(1, 4):
        claim = queue.claim(["prep"])
        assert claim.attempt == attempt
        if lease_failure:
            expire(queue, claim)
        else:
            queue.fail(claim, f"失敗{attempt}")
    assert queue.claim(["prep"]) is None
    job = read_job(queue, job_id)
    assert job.status == "failed" and job.attempts == 3
    assert job.failure_reason == ("リース期限切れ" if lease_failure else "失敗3")
    assert job.lease_token is None and job.run_id is None


def test_登録失敗はrunと結果と完了をロールバックする(queue, asset, tmp_path):
    job_id = queue.enqueue("color", asset, "a" * 64, {})
    claim = queue.claim(["color"])
    target = tmp_path / "output"
    temporary = temporary_path(target, str(claim.token))
    temporary.write_text("orphan")

    def broken(session, run):
        observation(asset)(session, run)
        session.flush()
        raise ValueError("登録途中の失敗")

    with pytest.raises(ValueError, match="登録途中"):
        queue.complete(claim, INFO, broken, [(temporary, target)])
    orphan = next(tmp_path.glob(".output-*/output"))
    assert orphan.read_text() == "orphan" and not target.exists()
    assert read_job(queue, job_id).status == "running"
    with Session(queue.engine) as session:
        assert session.scalar(select(func.count()).select_from(ColorObservation)) == 0
        assert session.scalar(select(func.count()).select_from(ProcessingRun)) == 0
    queue.fail(claim, "登録途中の失敗")
    retry = queue.claim(["color"])
    temporary = temporary_path(target, str(retry.token))
    temporary.write_text("committed")
    run_id = queue.complete(retry, INFO, observation(asset), [(temporary, target)])
    assert output(queue, run_id, target).read_text() == "committed"
    assert orphan.read_text() == "orphan"


def test_公開中に停止した旧試行が再開しても成功済み出力を上書きしない(
    queue, tmp_path, monkeypatch
):
    job_id = queue.enqueue("prep", None, "a" * 64, {})
    old = queue.claim(["prep"])
    target = tmp_path / "result"
    stale = temporary_path(target, str(old.token))
    stale.write_text("stale")
    paused = threading.Event()
    resume = threading.Event()
    replace = Path.replace

    def pause(path, destination):
        if path == stale:
            paused.set()
            assert resume.wait(10)
        return replace(path, destination)

    monkeypatch.setattr(Path, "replace", pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            queue.complete, old, INFO, lambda session, run: None, [(stale, target)]
        )
        try:
            assert paused.wait(5)
            # ファイルI/Oの停止中にも行ロックなしで回収できる。
            expire(queue, old)
            current = queue.claim(["prep"])
            fresh = temporary_path(target, str(current.token))
            fresh.write_text("fresh")
            run_id = queue.complete(current, INFO, lambda session, run: None, [(fresh, target)])
            published = output(queue, run_id, target)
        finally:
            resume.set()
        assert future.result(timeout=5) == run_id
    assert published.read_text() == "fresh"
    assert read_job(queue, job_id).run_id == run_id
    assert sorted(path.read_text() for path in tmp_path.glob(".output-*/result")) == [
        "fresh", "stale"
    ]


def test_所有権確認後にDB接続を失った旧取引は新試行の参照を変更しない(queue, tmp_path):
    job_id = queue.enqueue("prep", None, "a" * 64, {})
    old = queue.claim(["prep"])
    target = tmp_path / "result"
    stale = temporary_path(target, str(old.token))
    stale.write_text("stale")
    entered = threading.Event()
    resume = threading.Event()
    backend = []

    def disconnected(session, run):
        backend.append(session.scalar(text("SELECT pg_backend_pid()")))
        entered.set()
        assert resume.wait(10)

    def register(session, run):
        run.parameters = {"output": run.output_paths[str(target)]}

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(queue.complete, old, INFO, disconnected, [(stale, target)])
        try:
            assert entered.wait(5)
            with queue.engine.begin() as connection:
                assert connection.scalar(
                    text("SELECT pg_terminate_backend(:pid)"), {"pid": backend[0]}
                )
            expire(queue, old)
            current = queue.claim(["prep"])
            fresh = temporary_path(target, str(current.token))
            fresh.write_text("fresh")
            run_id = queue.complete(current, INFO, register, [(fresh, target)])
        finally:
            resume.set()
        with pytest.raises(DBAPIError):
            future.result(timeout=5)
    assert output(queue, run_id, target).read_text() == "fresh"
    assert read_job(queue, job_id).run_id == run_id
    with Session(queue.engine) as session:
        run = session.get(ProcessingRun, run_id)
        assert run.parameters["output"] == run.output_paths[str(target)]
        assert session.scalar(select(func.count()).select_from(ProcessingRun)) == 1


@pytest.mark.parametrize("idle", [True, False])
def test_完了取引の停止とSQL待機が上限後にロックを解放する(queue, idle):
    queue = Queue(queue.engine, lease=timedelta(seconds=0.4), timeout=0.2)
    queue.enqueue("prep", None, "a" * 64, {})
    old = queue.claim(["prep"])
    entered = threading.Event()
    resume = threading.Event()

    def blocked(session, run):
        entered.set()
        if idle:
            assert resume.wait(5)
        else:
            session.execute(text("SELECT pg_sleep(10)"))

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(queue.complete, old, INFO, blocked)
        try:
            assert entered.wait(5)
            assert queue.claim(["prep"]) is None
            deadline = monotonic() + 4
            current = None
            while current is None and monotonic() < deadline:
                sleep(0.05)
                current = queue.claim(["prep"])
            assert current is not None and current.attempt == 2
            queue.complete(current, INFO, lambda session, run: None)
        finally:
            resume.set()
        with pytest.raises(DBAPIError):
            future.result(timeout=5)


def test_停止ではDB返却の待機前に子を終了し待機上限で戻る(queue, tmp_path, monkeypatch):
    started = tmp_path / "started"
    stop = tmp_path / "stop"
    queue.enqueue("prep", None, "a" * 64, {"started": str(started), "delay": 30})
    claim = queue.claim(["prep"])
    worker = Worker(queue, {"prep": "tests.queue_handler"}, stop, poll_interval=0.02)
    waiting = threading.Event()
    release = threading.Event()
    stopped = threading.Event()
    real_stop = worker._stop

    def observe(process):
        real_stop(process)
        assert not process.is_alive()
        stopped.set()

    def fail(claim, reason):
        assert stopped.is_set()
        waiting.set()
        assert release.wait(10)

    monkeypatch.setattr(worker, "_stop", observe)
    monkeypatch.setattr(queue, "fail", fail)
    thread = threading.Thread(target=worker._run_claim, args=(claim,))
    thread.start()
    try:
        deadline = monotonic() + 10
        while not started.exists() and monotonic() < deadline:
            sleep(0.02)
        assert started.exists()
        before = monotonic()
        stop.touch()
        assert waiting.wait(3)
        thread.join(timeout=3)
        assert not thread.is_alive() and monotonic() - before < 3
        assert read_job(queue, claim.id).status == "running"
        expire(queue, claim)
        current = queue.claim(["prep"])
        assert current.attempt == 2
        queue.complete(current, INFO, lambda session, run: None)
    finally:
        release.set()
        stop.touch()
        thread.join(timeout=5)


def test_ロック中のジョブを飛ばしキューを分割して取得する(queue):
    first = queue.enqueue("segment", None, "a" * 64, {})
    second = queue.enqueue("segment", None, "b" * 64, {})
    queue.enqueue("collect", None, "c" * 64, {})
    with Session(queue.engine) as locked, locked.begin():
        locked.execute(select(Job).where(Job.id == first).with_for_update())
        claim = queue.claim(["segment"])
        assert claim.id == second
        assert queue.claim(["segment"]) is None
    assert queue.claim(["segment"]).id == first
    assert queue.claim(["review"]) is None


def test_リース更新と期限切れ更新の拒否(queue):
    job_id = queue.enqueue("shade", None, "a" * 64, {})
    claim = queue.claim(["shade"])
    before = read_job(queue, job_id).lease_until
    queue.renew(claim)
    assert read_job(queue, job_id).lease_until > before
    expire(queue, claim)
    with pytest.raises(LeaseLost):
        queue.renew(claim)


def test_停止フラグで計算を中断し別ワーカーで完了する(queue, tmp_path):
    started = tmp_path / "started"
    stop = tmp_path / "stop"
    job_id = queue.enqueue("prep", None, "a" * 64, {"started": str(started), "delay": 30})
    worker = Worker(queue, {"prep": "tests.queue_handler"}, stop, poll_interval=0.05)
    thread = threading.Thread(target=worker.run, kwargs={"once": True}, daemon=True)
    thread.start()
    try:
        deadline = monotonic() + 15
        while not started.exists() and monotonic() < deadline:
            sleep(0.05)
        assert started.exists(), "計算子プロセスが起動しませんでした"
        stop.touch()
        thread.join(timeout=5)
        assert not thread.is_alive(), "停止フラグで計算を中断できませんでした"
        assert read_job(queue, job_id).status == "pending"
        Worker(queue, {"prep": "tests.queue_handler"}, tmp_path / "stop-other").run(once=True)
        assert read_job(queue, job_id).status == "succeeded"
        assert started.read_text() == "2"
    finally:
        stop.touch()
        thread.join(timeout=5)


def test_計算例外を3回保存してワーカーが失敗を確定する(queue, tmp_path):
    job_id = queue.enqueue(
        "color", None, "a" * 64, {"started": str(tmp_path / "started"), "crash": True}
    )
    worker = Worker(queue, {"color": "tests.queue_handler"}, tmp_path / "stop")
    for _ in range(3):
        worker.run(once=True)
    job = read_job(queue, job_id)
    assert job.status == "failed" and "計算失敗" in job.failure_reason


def test_同時完了でも登録コールバックは一回だけ実行する(queue, asset):
    queue.enqueue("color", asset, "a" * 64, {})
    claim = queue.claim(["color"])

    def complete(_):
        return queue.complete(claim, INFO, observation(asset))

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(set(pool.map(complete, range(2)))) == 1
    with Session(queue.engine) as session:
        assert session.scalar(select(func.count()).select_from(ColorObservation)) == 1


def test_長い計算中はワーカーがリースを更新する(queue, tmp_path):
    queue = Queue(queue.engine, lease=timedelta(seconds=0.9))
    job_id = queue.enqueue(
        "prep", None, "a" * 64, {"started": str(tmp_path / "started"), "delay": 1.5}
    )
    Worker(queue, {"prep": "tests.queue_handler"}, tmp_path / "stop", poll_interval=0.05).run(
        once=True
    )
    job = read_job(queue, job_id)
    assert job.status == "succeeded" and job.attempts == 1
    with Session(queue.engine) as session:
        run = session.get(ProcessingRun, job.run_id)
        assert run.finished_at - run.started_at >= timedelta(seconds=1.5)


def test_計算プロセスの突然終了後も別ワーカーで完了する(queue, tmp_path):
    job_id = queue.enqueue(
        "prep", None, "a" * 64, {"started": str(tmp_path / "started"), "exit": True}
    )
    Worker(queue, {"prep": "tests.queue_handler"}, tmp_path / "stop").run(once=True)
    assert read_job(queue, job_id).status == "pending"
    Worker(queue, {"prep": "tests.queue_handler"}, tmp_path / "other-stop").run(once=True)
    assert read_job(queue, job_id).status == "succeeded"


def test_保存先の保留は試行数を消費せず古い所有権を拒否する(queue):
    job_id = queue.enqueue("prep", None, "a" * 64, {})
    old = queue.claim(["prep"])
    queue.defer(old, "保存先の復旧待ち")
    job = read_job(queue, job_id)
    assert job.status == "pending" and job.attempts == 0
    current = queue.claim(["prep"])
    assert current.attempt == 1 and current.token != old.token
    with pytest.raises(LeaseLost):
        queue.defer(old, "旧試行")
    queue.complete(current, INFO, lambda session, run: None)
    assert read_job(queue, job_id).status == "succeeded"


def test_子のreadonly例外は監視記録に先行しても失敗を消費しない(queue, tmp_path):
    job_id = queue.enqueue("prep", None, "a" * 64,
                           {"started": str(tmp_path / "started"), "readonly": True})
    worker = Worker(queue, {"prep": "tests.queue_handler"}, tmp_path / "stop")
    for _ in range(3):
        worker.run(once=True)
    job = read_job(queue, job_id)
    assert job.status == "pending" and job.attempts == 0
    assert "readonly" in job.failure_reason


def test_計算中の保存先異常は保留し復旧後に再開する(queue, tmp_path, monkeypatch):
    started = tmp_path / "started"
    job_id = queue.enqueue("prep", None, "a" * 64, {"started": str(started), "delay": 1})
    worker = Worker(queue, {"prep": "tests.queue_handler"}, tmp_path / "stop", poll_interval=0.02)
    available = threading.Event()
    available.set()
    monkeypatch.setattr(worker, "_available", lambda stage: available.is_set())
    thread = threading.Thread(target=worker.run, kwargs={"once": True}, daemon=True)
    thread.start()
    try:
        deadline = monotonic() + 15
        while not started.exists() and monotonic() < deadline:
            sleep(0.02)
        assert started.exists()
        available.clear()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert read_job(queue, job_id).attempts == 0
        assert read_job(queue, job_id).status == "pending"
        available.set()
        worker.run(once=True)
        assert read_job(queue, job_id).status == "succeeded"
        assert read_job(queue, job_id).attempts == 1
    finally:
        available.clear()
        thread.join(timeout=5)
