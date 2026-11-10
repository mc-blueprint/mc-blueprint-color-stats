"""本番監視用の集計状態だけを返す。画像・個別ID・所見は出力しない。"""

import json
import subprocess
import time
from pathlib import Path

ROOT = Path("/mnt/data/derived/issue114-terrain-20261110")


def read(path):
    return json.loads(path.read_text()) if path.exists() else None


def main():
    progress, audits = {}, {}
    for host in ("ubuntu1", "ubuntu2"):
        path = ROOT / host / "progress.json"
        data = read(path)
        if data:
            progress[host] = {**data, "age_seconds": round(time.time() - path.stat().st_mtime)}
        audits[host] = read(ROOT / host / "audit-full.json")
    names = ["colorstats-i114-ubuntu2-full-r3-resume1", "colorstats-i114-ubuntu2-audit-full-r3"]
    names += ["colorstats-i114-stats-" + action + "-r6b"
              for action in ("old-only", "combined", "preserve")]
    units = {}
    for name in names:
        output = subprocess.check_output([
            "systemctl", "show", name, "-p", "ActiveState", "-p", "Result", "-p", "MainPID",
            "-p", "LoadState", "-p", "CPUUsageNSec", "-p", "ExecMainStatus"], text=True)
        units[name] = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    artifacts = {"old": (ROOT / "old-held-baseline/summary.json").exists(),
                 "combined": (ROOT / "statistics/summary.json").exists(),
                 "preserved": (ROOT / "preservation-final.json").exists()}
    combined = read(ROOT / "statistics/comparison.json")
    artifacts["addition_comparison"] = bool(combined and "image_addition_only" in combined)
    print(json.dumps({"progress": progress, "audits": audits, "units": units,
                      "artifacts": artifacts}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
