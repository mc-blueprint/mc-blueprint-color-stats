import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ops.storage import monitor
from ops.storage.monitor import abnormal, should_remount_readonly, smart_values


class StorageMonitorTests(unittest.TestCase):
    def test_first_sample_establishes_baseline(self):
        self.assertFalse(abnormal(None, {"crc": 8, "reallocated": 0, "temperature": 30}))

    def test_counter_increase_is_abnormal(self):
        old = {"crc": 2, "reallocated": 0, "temperature": 30}
        self.assertTrue(abnormal(old, {"crc": 3, "reallocated": 0, "temperature": 31}))

    def test_temperature_threshold_is_abnormal(self):
        old = {"crc": 0, "reallocated": 0, "temperature": 30}
        self.assertTrue(abnormal(old, {"crc": 0, "reallocated": 0, "temperature": 60}))

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
