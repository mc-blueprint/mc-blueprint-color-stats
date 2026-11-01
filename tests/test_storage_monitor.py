import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from ops.storage import monitor
from ops.storage.monitor import abnormal, should_remount_readonly, smart_values


class StorageMonitorTests(unittest.TestCase):
    def test_first_sample_establishes_baseline(self):
        self.assertFalse(abnormal(None, {"crc": 8, "reallocated": 0, "temperature": 30}))

    def test_counter_increase_is_abnormal(self):
        old = {"crc": 2, "reallocated": 0, "temperature": 30}
        self.assertTrue(abnormal(old, {"crc": 3, "reallocated": 0, "temperature": 31}))

    def test_temperature_is_not_a_permanent_counter_abnormality(self):
        old = {"crc": 0, "reallocated": 0, "temperature": 30}
        self.assertFalse(abnormal(old, {"crc": 0, "reallocated": 0, "temperature": 60}))

    def test_smart_attributes_are_parsed(self):
        output = "199 UDMA_CRC_Error_Count 0x0032 100 100 000 Old_age Always - 19\n"
        self.assertEqual(smart_values(output)["crc"], 19)
        output = "194 Temperature_Celsius 0x0022 057 058 000 Old_age Always - 57 (0 8 0 0 0)\n"
        self.assertEqual(smart_values(output)["temperature"], 57)

    def test_nvme_temperature_is_parsed(self):
        self.assertEqual(smart_values("Temperature: 42 Celsius\n")["temperature"], 42)

    def test_kernel_logs_resume_from_saved_cursor_without_time_window(self):
        with TemporaryDirectory() as directory:
            cursor = Path(directory) / "kernel.cursor"
            output_by_cursor = {None: "first\nsecond\n", "cursor-2": "third\n"}
            commands = []

            def journalctl(command):
                commands.append(command)
                previous = cursor.read_text() if cursor.exists() else None
                output = output_by_cursor[previous]
                cursor.write_text("cursor-2" if previous is None else "cursor-3")
                return output

            with patch.object(monitor, "KERNEL_CURSOR", cursor), patch.object(
                monitor, "run", side_effect=journalctl
            ):
                self.assertEqual(monitor.kernel_logs(), "first\nsecond\n")
                self.assertEqual(monitor.kernel_logs(), "third\n")

            self.assertEqual(cursor.read_text(), "cursor-3")
            self.assertEqual(commands[0][0:3], ["journalctl", "-k", "-b"])
            self.assertEqual(commands[0][3:5], ["--cursor-file", str(cursor)])
            self.assertNotIn("--since", commands[0])
            self.assertEqual(commands[0], commands[1])

    def test_only_the_affected_raw_disk_is_remounted(self):
        disk = {"uuid": "raw-uuid", "raw": True}
        other = {"uuid": "other-uuid", "raw": True}
        event = [{"uuid": "raw-uuid", "reason": "smart_increase"}]
        self.assertTrue(should_remount_readonly(disk, event))
        self.assertFalse(should_remount_readonly(other, event))
        self.assertFalse(should_remount_readonly({"uuid": "raw-uuid", "raw": False}, event))


if __name__ == "__main__":
    unittest.main()


@pytest.mark.parametrize("line", ["I/O error, dev sda", "I/O error, dev sda2",
                                  "ata1: hard resetting link", "ata1.00: BadCRC"])
def test_parent_and_ata_kernel_errors(line):
    assert monitor.kernel_matches({"sda", "sda2", "ata1"}, [line])
    assert not monitor.kernel_matches({"sdb", "sdb2", "ata10"}, [line])


@pytest.mark.parametrize("code,reason", [(0, []), (8, ["smart_health"]),
                                        (64, []), (128, []), (32, ["smart_health"]), (2, None)])
def test_smart_exit_bits(code, reason):
    result = subprocess.CompletedProcess([], code, "Serial Number: serial\nTemperature: 35 Celsius")
    with (patch.object(Path, "resolve", return_value=Path("/dev/sda2")),
          patch.object(monitor, "device_names", return_value={"sda", "sda2", "ata1"}),
          patch.object(subprocess, "run", return_value=result)):
        if reason is None:
            with pytest.raises(ValueError, match="smart_unavailable"):
                monitor.inspect_disk({"uuid": "raw", "serial": "serial"}, None, [])
        else:
            assert monitor.inspect_disk({"uuid": "raw", "serial": "serial"}, None, [])[1] == reason


@pytest.mark.parametrize("failure", [FileNotFoundError("UUID missing"),
                                   ValueError("smart_unavailable: exit=2")])
def test_failed_medium_is_blocked_and_other_media_are_checked(tmp_path, monkeypatch, failure):
    config = tmp_path / "disks.json"
    disks = [{"uuid": "bad", "raw": True, "mount": "/missing"},
             {"uuid": "good", "raw": False}]
    config.write_text(json.dumps({"disks": disks}))
    for name, value in {"CONFIG": config, "STATE": tmp_path / "state.json",
                        "LOG": tmp_path / "events.jsonl", "BLOCKED": tmp_path / "blocked"}.items():
        monkeypatch.setattr(monitor, name, value)
    monkeypatch.setattr(monitor, "kernel_logs", lambda: "")
    monkeypatch.setattr(monitor, "run", lambda command: "wrong-uuid")
    with patch.object(monitor, "inspect_disk", side_effect=[failure, (
        {"crc": 0, "reallocated": 0, "temperature": 35}, [])
    ]) as inspect:
        monitor.main()
    assert inspect.call_count == 2
    assert (tmp_path / "blocked/bad").exists()
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["bad"]["error"] and state["good"]["temperature"] == 35
    assert "remount_failed" in (tmp_path / "events.jsonl").read_text()


@pytest.mark.parametrize("temperatures,blocked", [
    ([60, 59, 55, 54, 59, 60], [True, True, True, False, False, True]),
    ([59], [False]),
])
def test_temperature_hysteresis(temperatures, blocked):
    previous = None
    with (patch.object(Path, "resolve", return_value=Path("/dev/sda2")),
          patch.object(monitor, "device_names", return_value={"sda"})):
        for temperature, expected in zip(temperatures, blocked, strict=True):
            result = subprocess.CompletedProcess(
                [], 0, f"Serial Number: serial\nTemperature: {temperature} Celsius"
            )
            with patch.object(subprocess, "run", return_value=result):
                current, reasons = monitor.inspect_disk(
                    {"uuid": "raw", "serial": "serial"}, previous, []
                )
            assert current["temperature_blocked"] is expected
            assert reasons == (["temperature"] if expected else [])
            previous = current


@pytest.mark.parametrize("attribute,code,expected", [
    ("Airflow_Temperature_Cel", 32, []),
    ("Temperature_Celsius", 16, []),
    ("Airflow_Temperature_Cel", 40, ["smart_health"]),
    ("Reallocated_Sector_Ct", 32, ["smart_health"]),
])
def test_smart_threshold_temperature_is_distinguished_from_media_failure(attribute, code, expected):
    output = (f"Serial Number: serial\n190 {attribute} 0x0022 059 042 045 "
              "Old_age Always In_the_past 41\nTemperature: 41 Celsius")
    with (patch.object(Path, "resolve", return_value=Path("/dev/sda2")),
          patch.object(monitor, "device_names", return_value={"sda"}),
          patch.object(subprocess, "run", return_value=subprocess.CompletedProcess(
              [], code, output))):
        assert monitor.inspect_disk({"uuid": "raw", "serial": "serial"}, None, [])[1] == expected


def test_pending_sector_increase_is_permanent_abnormality():
    old = {"crc": 0, "reallocated": 0, "pending": 0, "temperature": 40}
    assert abnormal(old, {**old, "pending": 1})
    assert smart_values(
        "197 Current_Pending_Sector 0x0012 100 100 000 Old_age Always - 1"
    )["pending"] == 1


@pytest.mark.parametrize("text", ["", "199 UDMA_CRC_Error_Count -", "Temperature: unknown"])
def test_unreadable_smart_values_are_not_healthy_zeros(text):
    with pytest.raises(ValueError, match="SMART"):
        smart_values(text)
