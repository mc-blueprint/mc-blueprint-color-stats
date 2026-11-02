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
