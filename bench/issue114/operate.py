"""単独GPUの新しい#114実行だけをログ付きSSH経路で起動する。"""

import argparse
import json
import shlex
import sys
from pathlib import Path

from bench.issue122.runtime import HOST, PARTITION, remote_root


def command(args):
    root = remote_root(args.root)
    unit = "colorstats-i114-" + args.name + "-" + args.action
    if args.action == "status":
        units = ["colorstats-i114-" + args.name + "-" + phase
                 for phase in ("smoke", "full", "audit-smoke", "audit-full")]
        return shlex.join(["sudo", "-n", "systemctl", "show", *units,
                           "-p", "ActiveState", "-p", "Result", "-p", "ExecMainStatus"])
    options = ["sudo", "-n", "systemd-run", "--unit=" + unit,
               "--property=WorkingDirectory=" + args.code, "--property=UMask=0077",
               "--setenv=PYTHONPATH=" + args.code + "/src:" + args.code,
               "--setenv=PYTHONDONTWRITEBYTECODE=1", "--setenv=HF_HUB_OFFLINE=1",
               "--setenv=TRANSFORMERS_OFFLINE=1", "--setenv=TMPDIR=" + root + "/ubuntu1/tmp",
               "--setenv=XDG_CACHE_HOME=" + root + "/ubuntu1/cache"]
    for path in ("/srv/colorstats", "/mnt/data/derived/issue114-batch1-20261106"):
        options.append("--property=BindReadOnlyPaths=" + root + "/media/root" + path + ":" + path)
    options += [args.python, "-m", "bench.issue114.production",
                "audit" if args.action.startswith("audit") else "run", "--root", root,
                "--host", PARTITION, "--models", args.models]
    if args.action in {"smoke", "audit-smoke"}:
        options += ["--limit", "3"]
    return shlex.join(options)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("smoke", "full", "audit-smoke", "audit-full", "status"))
    for name in ("root", "code", "python", "models", "name"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(Path.home() / ".codex/scripts"))
    from ssh_logged import main as ssh

    targets = json.loads((root / ".ssh-targets.json").read_text(encoding="utf-8"))
    raise SystemExit(ssh(["--target", targets[HOST], "--directory", args.code,
                          "--project", str(root), "--command", command(args)]))


if __name__ == "__main__":
    main()
