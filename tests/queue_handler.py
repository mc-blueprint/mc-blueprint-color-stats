"""spawnされた計算プロセスで使う統合テスト用stage。"""

import errno
import os
import struct
from pathlib import Path
from time import sleep

from colorstats.queue import RunInfo
from colorstats.queue.worker import Prepared


def hang_before_receive(connection):
    sleep(60)


def hang_during_response(connection):
    _, claim = connection.recv()
    os.write(connection.fileno(), struct.pack("!i", 1024) + b"x")
    Path(claim.payload["started"]).touch()
    sleep(60)


def prepare(claim):
    started = Path(claim.payload["started"])
    started.write_text(str(claim.attempt), encoding="utf-8")
    if claim.payload.get("pids"):
        with Path(claim.payload["pids"]).open("a", encoding="utf-8") as stream:
            stream.write(f"{os.getpid()}\n")
    if claim.payload.get("readonly"):
        raise OSError(errno.EROFS, "保存先がreadonlyです")
    if claim.payload.get("io_error"):
        raise OSError(errno.EIO, "保存先のI/Oエラーです")
    if claim.payload.get("exit") and claim.attempt == 1:
        os._exit(17)
    if claim.payload.get("crash"):
        raise ValueError("計算失敗")
    if claim.attempt == 1:
        sleep(claim.payload.get("delay", 0))
    return Prepared(RunInfo("open", "test", "0.1.0", "test-worker", {
        "config_hash": claim.config_hash,
    }))


def register(session, run, data):
    pass


def image_gate_request(endpoint, body, key):
    """leaseより長いHTTP処理を外部通信なしで再現する。"""
    import json

    from tests.test_image_gate import response

    if os.environ.get("COLORSTATS_TEST_429") == "1":
        return {"status": 429, "request_id": "req_fixture", "retry_after": "300",
                "body": '{"error":{"code":"rate_limit_exceeded"}}'}
    if endpoint == "responses":
        sleep(2)
        result = response()
    else:
        result = {"object": "response.input_tokens", "input_tokens": 4000}
    return {"status": 200, "request_id": "req_fixture", "retry_after": None,
            "body": json.dumps(result)}


def image_gate_prepare(connection):
    """spawn先にだけ架空のHTTP応答・hostを設定し、実workerの処理へ渡す。"""
    import socket

    from colorstats import api_budget
    from colorstats.queue.worker import _prepare

    socket.gethostname = lambda: "ubuntu-1"
    api_budget.request = image_gate_request
    _prepare(connection)
