"""配備サービスの停止要求と障害終了を区別する。"""

from unittest.mock import Mock

import pytest
from ops.deploy import stop


@pytest.mark.parametrize("pid", [None, ""])
def test_no_mainpid_does_not_block_restart(tmp_path, pid):
    flag = tmp_path / "worker.stop"
    stop.stop(flag, pid)
    assert not flag.exists()


def test_dead_mainpid_does_not_block_restart(tmp_path, monkeypatch):
    flag = tmp_path / "worker.stop"
    monkeypatch.setattr(stop.os, "kill", Mock(side_effect=ProcessLookupError))
    stop.stop(flag, "123")
    assert not flag.exists()


def test_explicit_stop_sets_flag_and_waits_for_worker(tmp_path, monkeypatch):
    flag = tmp_path / "worker.stop"
    calls = []

    def alive(pid, signal):
        calls.append((pid, signal))
        if len(calls) == 3:
            assert flag.exists()
            raise ProcessLookupError

    monkeypatch.setattr(stop.os, "kill", alive)
    monkeypatch.setattr(stop, "sleep", lambda seconds: None)
    stop.stop(flag, "123")
    assert flag.exists()
    assert calls == [(123, 0)] * 3
