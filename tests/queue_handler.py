"""spawnされた計算プロセスで使う統合テスト用stage。"""

import errno
import os
from pathlib import Path
from time import sleep

from colorstats.queue import RunInfo
from colorstats.queue.worker import Prepared


def prepare(claim):
    started = Path(claim.payload["started"])
    started.write_text(str(claim.attempt), encoding="utf-8")
    if claim.payload.get("readonly"):
        raise OSError(errno.EROFS, "保存先がreadonlyです")
    if claim.payload.get("exit") and claim.attempt == 1:
        os._exit(17)
    if claim.payload.get("crash"):
        raise ValueError("計算失敗")
    if claim.attempt == 1:
        sleep(claim.payload.get("delay", 0))
    return Prepared(RunInfo("open", "test", "0.1.0", "test-worker", {}))


def register(session, run, data):
    pass
