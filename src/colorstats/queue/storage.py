"""ローカル保存先の欠落・readonlyと監視の停止記録を取得前に確認する。"""

import json
import os
from pathlib import Path

CONFIG = Path("/etc/colorstats-storage/disks.json")
BLOCKED = Path("/var/lib/colorstats-storage/blocked")


def storage_available(stage: str, paths: tuple[Path, ...] = ()) -> bool:
    """collect/prep/reviewは監視対象rawも確認する。追加pathsはstageの入出力root。"""
    try:
        roots = list(paths)
        if stage in ("collect", "prep", "review") and CONFIG.exists():
            for disk in json.loads(CONFIG.read_text())["disks"]:
                if disk.get("raw"):
                    if (BLOCKED / disk["uuid"]).exists():
                        return False
                    device = Path(f"/dev/disk/by-uuid/{disk['uuid']}")
                    if not device.exists():
                        return False
                    root = Path(disk["mount"])
                    if not root.is_mount() or root.stat().st_dev != device.stat().st_rdev:
                        return False
                    roots.append(root)
        return all(
            root.is_dir() and (
                not hasattr(os, "statvfs") or not os.statvfs(root).f_flag & os.ST_RDONLY
            )
            for root in roots
        )
    except (OSError, ValueError, KeyError):
        return False
