import multiprocessing
import sys
import threading
from collections import deque
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from time import monotonic
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from colorstats.queue import Claim, LeaseLost
from colorstats.queue.worker import Worker
from tests.queue_handler import hang_before_receive, hang_during_response


@pytest.mark.parametrize("recycle", [False, True])
@pytest.mark.parametrize("failure", ["exit", "crash"])
def test_resident_prepare_process_is_reused_and_restarted_after_exit(
    tmp_path, monkeypatch, recycle, failure
):
    if recycle:
        monkeypatch.setattr("colorstats.queue.worker.MAX_PREPARES", 1)
    pids = tmp_path / "pids"
    claims = deque(
        Claim(
            id=uuid4(),
            token=uuid4(),
            stage="prep",
            asset_id=None,
            config_hash=str(index),
            payload={
                "started": str(tmp_path / f"started-{index}"),
                "pids": str(pids),
                failure: index == 1 and attempt == 1,
            },
            attempt=attempt,
            started_at=datetime.now(UTC),
        )
        for index, attempt in ((1, 1), (1, 2), (2, 1))
    )
    stop = tmp_path / "stop"
    queue = Mock()
    queue.lease = timedelta(minutes=10)

    def claim(_stages):
        if claims:
            return claims.popleft()
        stop.touch()
        return None

    queue.claim.side_effect = claim
    worker = Worker(queue, {"prep": "tests.queue_handler"}, stop, poll_interval=0.01)
    worker._available = lambda _stage: True

    worker.run()

    assert queue.fail.call_count == 1
    assert queue.complete.call_count == 2
    first_pid, restarted_pid, reused_pid = pids.read_text().splitlines()
    assert (first_pid != restarted_pid) == (failure == "exit" or recycle)
    assert (restarted_pid != reused_pid) == recycle


@pytest.mark.parametrize("error", [LeaseLost("失効"), SQLAlchemyError("DB応答異常")])
def test_リース更新失敗では旧計算を捨て次の結果を取り違えない(tmp_path, error):
    stop = tmp_path / "stop"
    claims = deque(
        Claim(
            id=uuid4(), token=uuid4(), stage="prep", asset_id=None,
            config_hash=str(index),
            payload={"started": str(tmp_path / f"started-{index}"), "delay": delay},
            attempt=1, started_at=datetime.now(UTC),
        )
        for index, delay in ((1, 5), (2, 0))
    )
    current = claims[-1]
    queue = Mock()
    queue.lease = timedelta(seconds=3)
    queue.renew.side_effect = [error, None, None, None]

    def claim(_stages):
        if claims:
            return claims.popleft()
        stop.touch()
        return None

    queue.claim.side_effect = claim
    worker = Worker(queue, {"prep": "tests.queue_handler"}, stop, poll_interval=0.01)
    worker._available = lambda _stage: True
    worker.run()

    queue.complete.assert_called_once()
    assert queue.complete.call_args.args[0] == current
    assert queue.complete.call_args.args[1].parameters == {"config_hash": "2"}
    assert worker._process is None


@pytest.mark.parametrize("hang", [hang_before_receive, hang_during_response])
@pytest.mark.parametrize(
    "interrupt", ["stop", "lease", "database", "storage", "keyboard", "system_exit"]
)
def test_通信停止中もリース更新と中断が働く(tmp_path, monkeypatch, hang, interrupt):
    if hang is hang_during_response and sys.platform == "win32":
        pytest.skip("部分フレームの注入はPOSIXのパイプを使用する")
    claim = Claim(
        id=uuid4(), token=uuid4(), stage="prep", asset_id=None, config_hash="1",
        payload={"started": str(tmp_path / "started"), "padding": "x" * (2 * 1024 * 1024)},
        attempt=1, started_at=datetime.now(UTC),
    )
    queue = Mock()
    queue.lease = timedelta(seconds=0.3)
    queue.claim.return_value = claim
    stop = tmp_path / "stop"
    worker = Worker(queue, {"prep": "tests.queue_handler"}, stop, poll_interval=0.01)
    worker._available = lambda _stage: True
    error = {"keyboard": KeyboardInterrupt(), "system_exit": SystemExit(7)}.get(interrupt)

    def renew(_claim):
        if queue.renew.call_count < 2:
            return
        if hang is hang_during_response and not (tmp_path / "started").exists():
            return
        if interrupt == "stop":
            stop.touch()
        elif interrupt == "storage":
            worker._available = lambda _stage: False
        elif interrupt == "lease":
            raise LeaseLost("失効")
        elif error is not None:
            raise error
        else:
            raise SQLAlchemyError("DB応答異常")

    queue.renew.side_effect = renew

    def unblock():
        if worker._process is not None and worker._process.is_alive():
            worker._process.terminate()

    watchdog = threading.Timer(8, unblock)
    threads = set(threading.enumerate())
    started = monotonic()
    with monkeypatch.context() as patch:
        patch.setattr("colorstats.queue.worker._prepare", hang)
        watchdog.start()
        try:
            with pytest.raises(type(error)) if error is not None else nullcontext() as caught:
                worker.run(once=True)
            if error is not None:
                assert caught.value is error
        finally:
            watchdog.cancel()
            watchdog.join()
            worker._close_prepare()
    assert monotonic() - started < 4
    assert queue.renew.call_count >= 2
    queue.complete.assert_not_called()
    if interrupt == "storage":
        queue.defer.assert_called_once()
        queue.fail.assert_not_called()
    elif interrupt == "lease" or error is not None:
        queue.fail.assert_not_called()
    else:
        queue.fail.assert_called_once()
    assert worker._process is None
    assert not multiprocessing.active_children()
    assert set(threading.enumerate()) <= threads

    stop.unlink(missing_ok=True)
    worker._available = lambda _stage: True
    queue.lease = timedelta(minutes=10)
    try:
        worker._run_claim(claim)
        queue.complete.assert_called_once()
    finally:
        worker._stop_prepare()
