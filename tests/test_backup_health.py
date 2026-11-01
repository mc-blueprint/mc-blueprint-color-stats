import json
from unittest.mock import patch

from ops.backup import health

UUID = "new-uuid"
DISKS = [{"uuid": UUID, "previous_uuids": ["old-uuid"]}]
STATE = {UUID: {"temperature": 40, "crc": 0, "reallocated": 0}}


def test_healthy_medium_is_allowed():
    assert health.exclusion_reason(UUID, STATE, [], DISKS) == ""


def test_hot_medium_is_excluded():
    state = {UUID: {**STATE[UUID], "temperature": 60}}
    assert "temperature=60C" in health.exclusion_reason(UUID, state, [], DISKS)


def test_recorded_crc_or_reallocation_increase_is_excluded():
    for attribute in ("crc", "reallocated"):
        event = {
            "uuid": UUID,
            "reason": "smart_increase",
            "previous": STATE[UUID],
            "current": {**STATE[UUID], attribute: 1},
        }
        assert "smart_increase" in health.exclusion_reason(UUID, STATE, [event], DISKS)


def test_previous_uuid_history_is_preserved_and_other_media_are_allowed():
    event = {"uuid": "old-uuid", "reason": "smart_increase", "current": {"temperature": 61}}
    assert "61" in health.exclusion_reason(UUID, STATE, [event], DISKS)
    assert health.exclusion_reason(UUID, STATE, [{**event, "uuid": "other"}], DISKS) == ""


def test_missing_or_stale_state_fails_closed(tmp_path, capsys):
    state = tmp_path / "state.json"
    with (
        patch.object(health, "STATE", state),
        patch.object(health, "EVENTS", tmp_path / "events.jsonl"),
        patch.object(health, "CONFIG", tmp_path / "disks.json"),
        patch("sys.argv", ["health.py", UUID]),
    ):
        assert health.main() == 1
        assert "monitor_unavailable" in capsys.readouterr().out
        state.write_text(json.dumps(STATE))
        with patch.object(health.time, "time", return_value=state.stat().st_mtime + 901):
            assert health.main() == 1
            assert "15分" in capsys.readouterr().out
