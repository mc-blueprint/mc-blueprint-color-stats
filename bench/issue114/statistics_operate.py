"""#114の統計・診断・保全を、旧媒体の読取り専用bindで記録付き起動する。"""

import argparse
import json
import shlex
import sys
from pathlib import Path

ROOT = "/mnt/data/derived/issue114-terrain-20261110"
CODE = "/mnt/data/work/issue114-statistics-r7"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("diagnostic", "old-only", "combined",
                                           "preserve", "status"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(Path.home() / ".codex/scripts"))
    from ssh_logged import main as ssh

    if args.action == "status":
        command = "sudo -n systemctl show " + " ".join(
            "colorstats-i114-stats-" + action + "-r6b.service"
            for action in ("diagnostic", "old-only", "combined", "preserve")) + (
                " -p Id -p ActiveState -p Result -p ExecMainStatus -p MainPID -p InvocationID")
    else:
        code = "/mnt/data/work/issue114-audit-r8" if args.action == "preserve" else CODE
        unit = "--unit=colorstats-i114-stats-" + args.action + "-r6b"
        options = ["sudo", "-n", "systemd-run", unit,
                   "--property=WorkingDirectory=" + ROOT, "--property=UMask=0077",
                   "--setenv=PYTHONPATH=" + code + "/src:" + code,
                   "--setenv=PYTHONDONTWRITEBYTECODE=1",
                   "--setenv=TMPDIR=" + ROOT + "/ubuntu2/tmp",
                   "--setenv=XDG_CACHE_HOME=" + ROOT + "/ubuntu2/cache"]
        for path in ("/srv/colorstats", "/mnt/data/derived/pilot-m1",
                     "/mnt/data/derived/issue114-batch1-20261106"):
            options.append("--property=BindReadOnlyPaths=" + ROOT +
                           "/media/root" + path + ":" + path)
        module = {"diagnostic": "diagnostic", "old-only": "terrain_statistics",
                  "combined": "terrain_statistics", "preserve": "preservation"}[args.action]
        options += ["/mnt/data/work/issue-76/venv/bin/python", "-m", "bench.issue114." + module]
        if args.action == "old-only":
            options.append("--old-only")
        command = shlex.join(options)
    targets = json.loads((root / ".ssh-targets.json").read_text(encoding="utf-8"))
    raise SystemExit(ssh(["--target", targets["ubuntu-2"], "--directory", "/mnt/data/work",
                          "--project", str(root), "--command", command]))


if __name__ == "__main__":
    main()
