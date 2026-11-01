import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from colorstats.queue import storage
from colorstats.queue.worker import Worker


def test_readonly_stage_is_not_claimed_but_other_stage_continues(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "CONFIG", tmp_path / "missing")
    monkeypatch.setattr(storage.os, "ST_RDONLY", 1, raising=False)
    monkeypatch.setattr(storage.os, "statvfs", lambda path: SimpleNamespace(
        f_flag=storage.os.ST_RDONLY if path == tmp_path else 0
    ), raising=False)
    other = tmp_path / "other"
    other.mkdir()
    queue = Mock()
    queue.claim.return_value = None
    Worker(queue, {"collect": "unused", "color": "unused"}, tmp_path / "stop",
           storage_paths={"collect": (tmp_path,), "color": (other,)}).run(once=True)
    queue.claim.assert_called_once_with(("color",))


def test_monitor_block_and_missing_medium_stop_raw_stages(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"disks": [{"raw": True, "uuid": "raw",
                                            "mount": str(tmp_path)}]}))
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    marker = blocked / "raw"
    marker.touch()
    monkeypatch.setattr(storage, "CONFIG", config)
    monkeypatch.setattr(storage, "BLOCKED", blocked)
    assert not storage.storage_available("collect")
    assert not storage.storage_available("prep")
    assert storage.storage_available("color")
    marker.unlink()
    assert not storage.storage_available("collect")


def test_missing_output_root_stops_stage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "CONFIG", tmp_path / "missing")
    assert not storage.storage_available("color", (tmp_path / "absent",))
    assert storage.storage_available("color", (Path(tmp_path),))
