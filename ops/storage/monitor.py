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
BLOCKED = STATE.parent / "blocked"
BAD = re.compile(r"badcrc|I/O error|hard resetting link|resetting link", re.I)
ATTRIBUTES = {
    "UDMA_CRC_Error_Count": "crc",
    "Reallocated_Sector_Ct": "reallocated",
    "Current_Pending_Sector": "pending",
    "Airflow_Temperature_Cel": "temperature",
    "Temperature_Celsius": "temperature",
    "Temperature_Internal": "temperature",
}


def abnormal(previous, current):
    """SMARTのCRC・代替セクタ・保留セクタの増分を媒体異常とする。"""
    return (
        previous is not None and not previous.get("error")
        and any(current.get(key, 0) > previous.get(key, 0)
                for key in ("crc", "reallocated", "pending"))
    )


def smart_values(text):
    values = {"crc": 0, "reallocated": 0, "pending": 0, "temperature": 0}
    found = False
    for line in text.splitlines():
        fields = line.split()
        if fields[:1] == ["Temperature:"] and len(fields) > 1:
            try:
                values["temperature"] = int(fields[1])
                found = True
            except ValueError:
                raise ValueError("SMART温度を解析できません") from None
        for name, key in ATTRIBUTES.items():
            if name in fields:
                try:
                    raw = fields[9]
                    values[key] = int(raw)
                    found = True
                except (ValueError, IndexError):
                    raise ValueError("SMART属性を解析できません") from None
    if not found:
        raise ValueError("SMART計測値がありません")
    return values


def should_remount_readonly(disk, events):
    return disk.get("raw") and any(event.get("uuid") == disk["uuid"] for event in events)


def run(command):
    return subprocess.run(command, check=True, capture_output=True, text=True, timeout=30).stdout


def device_names(device):
    """partition・親ディスク・sysfs上のATAポートをkernel照合名として返す。"""
    parent = run(["lsblk", "-ndo", "PKNAME", str(device)]).strip()
    name = parent or device.name
    sysfs = (Path("/sys/class/block") / name).resolve(strict=True)
    return {device.name, name, *re.findall(r"\bata\d+\b", str(sysfs))}


def kernel_matches(names, lines):
    return any(
        re.search(rf"(?<![\w]){re.escape(name)}(?:\d+)?(?![\w])", line)
        if not name.startswith("ata")
        else re.search(rf"(?<![\w]){re.escape(name)}(?!\d)", line)
        for name in names for line in lines
    )


def inspect_disk(disk, previous, matched):
    device = Path(f"/dev/disk/by-uuid/{disk['uuid']}").resolve(strict=True)
    names = device_names(device)
    result = subprocess.run(
        ["smartctl", "-i", "-H", "-A", str(device)],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode < 0 or result.returncode & 7:
        raise ValueError(f"smart_unavailable: exit={result.returncode}")
    if disk["serial"] not in result.stdout:
        raise ValueError("serial_mismatch")
    current = smart_values(result.stdout)
    current["smart_exit"] = result.returncode
    current["failed_attributes"] = [
        fields[1] for line in result.stdout.splitlines()
        if len(fields := line.split()) >= 10 and fields[0].isdigit()
        and fields[8] in ("FAILING_NOW", "In_the_past")
    ]
    old = previous or {}
    current["temperature_blocked"] = current["temperature"] >= 60 or (
        (old.get("temperature_blocked", False) or old.get("temperature", 0) >= 60)
        and current["temperature"] >= 55
    )
    reasons = []
    temperature_only = current["failed_attributes"] and all(
        ATTRIBUTES.get(name) == "temperature" for name in current["failed_attributes"]
    )
    if result.returncode & 8 or (result.returncode & 48 and not temperature_only):
        reasons.append("smart_health")
    if abnormal(previous, current):
        reasons.append("smart_increase")
    if current["temperature_blocked"]:
        reasons.append("temperature")
    if kernel_matches(names, matched):
        reasons.append("kernel")
    return current, reasons


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
    try:
        matched = [line for line in kernel_logs().splitlines() if BAD.search(line)]
        kernel_error = None
    except (OSError, subprocess.SubprocessError) as error:
        matched = []
        kernel_error = str(error)
    for disk in config["disks"]:
        previous = state.get(disk["uuid"])
        try:
            current, reasons = inspect_disk(disk, previous, matched)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            current = {**(previous or {}), "error": str(error)}
            reasons = ["inspection_failed"]
        if kernel_error:
            reasons.append("kernel_unavailable")
        for reason in reasons:
            events.append({"uuid": disk["uuid"], "reason": reason,
                           "previous": previous, "current": current})
        state[disk["uuid"]] = current
        if should_remount_readonly(disk, events):
            BLOCKED.mkdir(parents=True, exist_ok=True)
            (BLOCKED / disk["uuid"]).touch()
            try:
                mounted = run(["findmnt", "-n", "-o", "UUID", "--mountpoint", disk["mount"]])
                if mounted.strip() != disk["uuid"]:
                    raise ValueError("mount_uuid_mismatch")
                run(["mount", "-o", "remount,ro", disk["mount"]])
                events.append({"uuid": disk["uuid"], "reason": "remounted_readonly"})
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                events.append({"uuid": disk["uuid"], "reason": "remount_failed",
                               "error": str(error)})
    STATE.write_text(json.dumps(state, indent=2) + "\n")
    if events:
        with LOG.open("a") as stream:
            for event in events:
                stream.write(json.dumps(event) + "\n")


if __name__ == "__main__":
    main()
