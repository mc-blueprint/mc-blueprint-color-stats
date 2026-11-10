"""許可されたGit管理下の実行コードをLAN内の専用配置へ転送する。"""

import argparse
import hashlib
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--issue", choices=("122", "114"), default="122")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(Path.home() / ".codex/scripts"))
    from run_logged import run_logged
    from ssh_logged import main as ssh

    paths = ["src", "configs", "taxonomy", "pyproject.toml", "uv.lock", "alembic.ini",
             "ops/deploy/m3_analysis.py", "ops/deploy/launch.py", "ops/deploy/raw-replica.py",
             "bench/issue47/benchmark.py", "bench/issue73/plan.json",
             "bench/issue121/decision.json", "bench/issue121/handoff.json",
             "bench/issue121/freeze.json"]
    tracked = subprocess.check_output(
        ["git", "ls-files", "--", *paths, "bench/issue122/*.py"], cwd=root,
    ).decode().splitlines()
    if args.issue == "114":
        tracked.extend(str(path.relative_to(root)).replace("\\", "/")
                       for path in (root / "bench/issue114").glob("*.py"))
    subprocess.run(["git", "rev-parse", "--verify", args.revision], cwd=root, check=True)
    if not tracked:
        raise ValueError("Git管理下の転送対象がありません")
    directory = root / ("data/issue" + args.issue)
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / (args.name + ".tar")
    with tarfile.open(archive, "x") as output:
        if args.issue == "114":
            directories = {str(parent).replace("\\", "/") for name in tracked
                           for parent in Path(name).parents if str(parent) != "."}
            for name in sorted(directories, key=lambda item: (item.count("/"), item)):
                entry = tarfile.TarInfo(name)
                entry.type = tarfile.DIRTYPE
                entry.mode = 0o700
                entry.uid = entry.gid = 65534
                output.addfile(entry)
        for name in sorted(set(tracked)):
            content = (root / name).read_bytes()
            entry = tarfile.TarInfo(name)
            entry.size = len(content)
            entry.mode = 0o600
            if args.issue == "114":
                entry.uid = entry.gid = 65534
            output.addfile(entry, io.BytesIO(content))
    checksum = hashlib.file_digest(archive.open("rb"), "sha256").hexdigest()
    print(json.dumps({"archive": archive.name, "sha256": checksum, "files": len(tracked)}),
          flush=True)
    targets = json.loads((root / ".ssh-targets.json").read_text())
    destinations = {
        "ubuntu-1": "/opt/colorstats/work/issue114-" + args.name,
        "ubuntu-2": "/mnt/data/work/issue114-" + args.name,
    } if args.issue == "114" else {
        "ubuntu-1": "/opt/colorstats/work/issue122-20261109/" + args.name,
        "ubuntu-2": "/mnt/data/work/issue-122/code-20261109/" + args.name,
    }
    for host, destination in destinations.items():
        temporary = "/tmp/colorstats-" + args.name + "-" + checksum[:16] + ".tar"
        result = run_logged([
            "scp", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            str(archive), targets[host] + ":" + temporary,
        ])
        if result:
            raise SystemExit(result)
        owner = " -o 65534 -g 65534" if args.issue == "114" else ""
        extraction = "--same-owner" if args.issue == "114" else "--no-same-owner"
        command = (
            "set -eu; test ! -e " + destination + "; "
            + "echo '" + checksum + "  " + temporary + "' | sha256sum -c -; "
            + "sudo -n install -d -m 700" + owner + " " + destination + "; "
            + "sudo -n tar " + extraction + " -xf " + temporary + " -C " + destination + "; "
            + "sudo -n install -m 600 " + temporary + " " + destination + "/code.tar; "
            + "sudo -n sha256sum " + destination + "/code.tar"
        )
        result = ssh(["--target", targets[host], "--directory", "/tmp", "--project",
                      str(root), "--command", command])
        if result:
            raise SystemExit(result)


if __name__ == "__main__":
    main()
