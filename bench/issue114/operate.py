"""登録済みGPUの#114専用unitを、固定版と読取り専用媒体bindで起動する。"""

import argparse
import json
import shlex
import sys
from pathlib import Path

ROOT = "/mnt/data/derived/issue114-terrain-20261110"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("smoke", "full", "audit-smoke", "audit-full", "status"))
    parser.add_argument("--host", choices=("ubuntu1", "ubuntu2"), required=True)
    parser.add_argument("--attempt", choices=("r3", "r3-resume1"), default="r3")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(Path.home() / ".codex/scripts"))
    from ssh_logged import main as ssh

    first = args.host == "ubuntu1"
    host = "ubuntu-1" if first else "ubuntu-2"
    code = ("/opt/colorstats/work/" if first else "/mnt/data/work/") + "issue114-execution-r3"
    python = ("/opt/colorstats/work/issue66-20261104/.venv/bin/python" if first
              else "/mnt/data/work/issue-40/venv/bin/python")
    models = ("/opt/colorstats/work/issue66-20261104/models" if first
              else "/mnt/data/work/issue-40/models")
    if args.action == "status":
        command = "sudo -n systemctl show " + " ".join(
            "colorstats-i114-" + args.host + "-" + stage + "-" +
            (args.attempt if stage == "full" else "r3") + ".service"
            for stage in ("smoke", "full", "audit-smoke", "audit-full")) + (
                " -p Id -p ActiveState -p Result -p ExecMainStatus -p InvocationID")
    else:
        suffix = args.attempt if args.action == "full" else "r3"
        options = ["sudo", "-n", "systemd-run", "--unit=colorstats-i114-" + args.host +
                   "-" + args.action + "-" + suffix, "--property=WorkingDirectory=" + code,
                   "--property=UMask=0077", "--setenv=PYTHONPATH=" + code + "/src:" + code,
                   "--setenv=PYTHONDONTWRITEBYTECODE=1", "--setenv=HF_HUB_OFFLINE=1",
                   "--setenv=TRANSFORMERS_OFFLINE=1",
                   "--setenv=TMPDIR=" + ROOT + "/" + args.host + "/tmp",
                   "--setenv=XDG_CACHE_HOME=" + ROOT + "/" + args.host + "/cache"]
        for path in ("/srv/colorstats", "/mnt/data/derived/issue114-batch1-20261106"):
            options.append("--property=BindReadOnlyPaths=" + ROOT +
                           "/media/root" + path + ":" + path)
        options.append(python)
        if first:
            options.append(code + "/ops/deploy/launch.py")
        options += ["-m", "bench.issue114.production", "audit" if args.action.startswith("audit")
                    else "run", "--host", args.host,
                    "--models", models]
        if args.action in {"smoke", "audit-smoke"}:
            options += ["--limit", "3"]
        command = shlex.join(options)
    targets = json.loads((root / ".ssh-targets.json").read_text(encoding="utf-8"))
    directory = "/opt" if first else "/mnt/data/work"
    raise SystemExit(ssh(["--target", targets[host], "--directory", directory,
                          "--project", str(root), "--command", command]))


if __name__ == "__main__":
    main()
