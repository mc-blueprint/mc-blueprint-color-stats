#!/usr/bin/env python3
"""SMART・kernelログの増分を記録し、raw媒体の異常時にreadonly化する。"""

import json
import re
import subprocess
from pathlib import Path

STATE = Path("/var/lib/colorstats-storage/state.json")
KERNEL_CURSOR = STATE.parent / "kernel.cursor"
LOG = Path("/var/log/colorstats-storage/events.jsonl")
CONFIG = Path("/etc/colorstats-storage/disks.json")
BAD = re.compile(r"badcrc|I/O error|hard resetting link|resetting link", re.I)
ATTRIBUTES = {
    "UDMA_CRC_Error_Count": "crc",
    "Reallocated_Sector_Ct": "reallocated",
    "Temperature_Celsius": "temperature",
    "Temperature_Internal": "temperature",
}


def abnormal(previous, current):
    """SMARTのCRC・代替セクタの増加または60度以上を異常とする。"""
    if previous is None:
        return False
    return (
        any(current[key] > previous[key] for key in ("crc", "reallocated"))
        or current["temperature"] >= 60
    )


def smart_values(text):
    values = {"crc": 0, "reallocated": 0, "temperature": 0}
    for line in text.splitlines():
        fields = line.split()
        if fields[:1] == ["Temperature:"] and len(fields) > 1:
            try:
                values["temperature"] = int(fields[1])
            except ValueError:
                pass
        for name, key in ATTRIBUTES.items():
            if name in fields:
                try:
                    raw = fields[fields.index("-") + 1]
                    values[key] = int(raw)
                except ValueError:
                    pass
    return values


def should_remount_readonly(disk, events):
    return disk.get("raw") and any(event.get("uuid") == disk["uuid"] for event in events)


def run(command):
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout


def kernel_logs():
    return run(
        [
            "journalctl",
            "-k",
            "-b",
            "--cursor-file",
            str(KERNEL_CURSOR),
            "--no-pager",
            "-o",
            "cat",
        ]
    )


def main():
    STATE.parent.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    config = json.loads(CONFIG.read_text())
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    events = []
    for disk in config["disks"]:
        device = str(Path(f"/dev/disk/by-uuid/{disk['uuid']}").resolve(strict=True))
        if disk["serial"] not in run(["smartctl", "-i", device]):
            events.append({"uuid": disk["uuid"], "reason": "serial_mismatch"})
            continue
        current = smart_values(run(["smartctl", "-A", device]))
        old = state.get(disk["uuid"])
        if abnormal(old, current):
            events.append(
                {
                    "uuid": disk["uuid"],
                    "reason": "smart_increase",
                    "previous": old,
                    "current": current,
                }
            )
        state[disk["uuid"]] = current

    kernel = kernel_logs()
    matched = [line for line in kernel.splitlines() if BAD.search(line)]
    for disk in config["disks"]:
        device = str(Path(f"/dev/disk/by-uuid/{disk['uuid']}").resolve(strict=True))
        if any(re.search(rf"\b{re.escape(Path(device).name)}\b", line) for line in matched):
            events.append({"uuid": disk["uuid"], "reason": "kernel"})
        if should_remount_readonly(disk, events):
            if subprocess.run(["mountpoint", "-q", disk["mount"]]).returncode == 0:
                subprocess.run(["mount", "-o", "remount,ro", disk["mount"]], check=True)
                events.append({"uuid": disk["uuid"], "reason": "remounted_readonly"})
    STATE.write_text(json.dumps(state, indent=2) + "\n")
    if events:
        with LOG.open("a") as stream:
            for event in events:
                stream.write(json.dumps(event) + "\n")


if __name__ == "__main__":
    main()
