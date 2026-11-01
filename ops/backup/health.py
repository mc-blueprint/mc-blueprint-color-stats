#!/usr/bin/env python3
"""既存監視の状態・異常記録から、指定UUIDへの転送可否を返す。"""

import json
import sys
import time
from pathlib import Path

STATE = Path("/var/lib/colorstats-storage/state.json")
EVENTS = Path("/var/log/colorstats-storage/events.jsonl")
CONFIG = Path("/etc/colorstats-storage/disks.json")


def exclusion_reason(uuid, state, events, disks):
    """異常理由を返す。空文字は転送可能。旧UUIDの記録も原因確認まで引き継ぐ。"""
    disk = next(disk for disk in disks if disk["uuid"] == uuid)
    current = state[uuid]
    if current.get("error"):
        return f"inspection_failed: {current['error']}"
    if current["temperature"] >= 60 or current.get("temperature_blocked"):
        return f"temperature={current['temperature']}C (60C以上で停止、55C未満で復帰)"
    identities = {uuid, *disk.get("previous_uuids", [])}
    for event in events:
        if event["uuid"] in identities:
            if event["reason"] in ("temperature", "temperature_history"):
                continue
            if event["reason"] == "smart_increase":
                previous = event.get("previous")
                sample = event.get("current", {})
                if (previous and not previous.get("error") and sample.get("temperature", 0) >= 60
                        and all(key in previous and key in sample
                                and sample[key] <= previous[key]
                                for key in ("crc", "reallocated"))
                        and sample.get("pending", 0) <= previous.get("pending", 0)):
                    continue
            return json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return ""


def main():
    uuid = sys.argv[1]
    try:
        state = json.loads(STATE.read_text())
        if time.time() - STATE.stat().st_mtime > 900:
            raise ValueError("監視状態が15分以上更新されていません")
        events = (
            [json.loads(line) for line in EVENTS.read_text().splitlines() if line]
            if EVENTS.exists()
            else []
        )
        disks = json.loads(CONFIG.read_text())["disks"]
        reason = exclusion_reason(uuid, state, events, disks)
    except (OSError, ValueError, KeyError, StopIteration) as error:
        reason = f"monitor_unavailable: {error}"
    if reason:
        print(f"uuid={uuid} excluded: {reason}")
        return 1
    print(f"uuid={uuid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
