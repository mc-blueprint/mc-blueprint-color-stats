"""現行hostで、新しい旧のみ／旧＋新の比較統計を記録付き起動する。"""

import argparse
import json
import shlex
import sys
from pathlib import Path

from bench.issue122.runtime import HOST, remote_root


def command(args):
    root, output = remote_root(args.root), remote_root(args.output)
    unit = "colorstats-i114-stats-" + args.name + "-" + args.action
    if args.action == "status":
        units = ["colorstats-i114-stats-" + args.name + "-" + phase
                 for phase in ("old-only", "combined")]
        return shlex.join(["sudo", "-n", "systemctl", "show", *units,
                           "-p", "ActiveState", "-p", "Result", "-p", "ExecMainStatus"])
    options = ["sudo", "-n", "systemd-run", "--unit=" + unit,
               "--property=WorkingDirectory=" + args.code, "--property=UMask=0077",
               "--setenv=PYTHONPATH=" + args.code + "/src:" + args.code,
               "--setenv=PYTHONDONTWRITEBYTECODE=1",
               "--setenv=TMPDIR=" + root + "/ubuntu1/tmp",
               "--setenv=XDG_CACHE_HOME=" + root + "/ubuntu1/cache"]
    for path in ("/srv/colorstats", "/mnt/data/derived/pilot-m1",
                 "/mnt/data/derived/issue114-batch1-20261106"):
        options.append("--property=BindReadOnlyPaths=" + root + "/media/root" + path + ":" + path)
    options += [args.python, "-m", "bench.issue114.terrain_statistics", "--root", root,
                "--output", output, "--baseline", args.baseline,
                "--baseline-snapshot", args.baseline_snapshot, "--policy", args.policy]
    if args.action == "old-only":
        options.append("--old-only")
    else:
        if not args.old_only_output:
            raise ValueError("比較には旧のみ統計の出力先が必要です")
        options += ["--old-only-output", remote_root(args.old_only_output)]
    return shlex.join(options)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("old-only", "combined", "status"))
    for name in ("root", "output", "code", "python", "baseline", "baseline-snapshot",
                 "policy", "name"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--old-only-output")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(Path.home() / ".codex/scripts"))
    from ssh_logged import main as ssh

    targets = json.loads((root / ".ssh-targets.json").read_text(encoding="utf-8"))
    raise SystemExit(ssh(["--target", targets[HOST], "--directory", args.code,
                          "--project", str(root), "--command", command(args)]))


if __name__ == "__main__":
    main()
