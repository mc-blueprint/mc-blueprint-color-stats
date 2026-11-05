"""M3と同じ読取り権限・低優先度で既存snapshot CLIを実行する。"""

import hashlib
import json
import os
import pwd
import subprocess
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

import psycopg
from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL

from colorstats.stats import snapshot, snapshot_cli

code = Path(__file__).resolve().parents[2]
base = code.parent
started = monotonic()
root = Path("/mnt/data/derived/stats") / (
    "issue104-full-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
)
root.mkdir(mode=0o700, exist_ok=False)
selection = Path("/mnt/data/derived/stats/issue74-full-20261104T180829Z/selection.json")
(root / "selection.json").write_bytes(selection.read_bytes())
implementation = {
    str(path.relative_to(code)): hashlib.sha256(path.read_bytes()).hexdigest()
    for directory in ("src", "configs", "taxonomy")
    for path in sorted((code / directory).rglob("*"))
    if path.is_file() and "__pycache__" not in path.parts
}
version = "5ffa603+i104-v2-" + snapshot.digest(implementation)[:16]
(root / "implementation.json").write_text(snapshot.canonical({
    "code_version": version, "files": implementation,
}) + "\n", encoding="utf-8")
with (base / (root.name + "-output.txt")).open("x", encoding="utf-8") as stream:
    stream.write(str(root) + "\n")
account = pwd.getpwnam("postgres")


def connect():
    previous = os.geteuid()
    os.seteuid(account.pw_uid)
    try:
        return psycopg.connect(dbname="colorstats", options=(
            "-c default_transaction_read_only=on -c application_name=colorstats-issue104-snapshot"
        ))
    finally:
        os.seteuid(previous)


engine = create_engine(URL.create("postgresql+psycopg"), creator=connect, hide_parameters=True)


@event.listens_for(engine, "connect")
def low_priority(connection, record):
    pid = connection.info.backend_pid
    os.setpriority(os.PRIO_PROCESS, pid, 19)
    subprocess.run(["ionice", "-c", "3", "-p", str(pid)], check=True)


original_read, original_groups = snapshot._read, snapshot._groups
processed = 0


def read(*args):
    result = original_read(*args)
    print(snapshot.canonical({"phase": "read_complete", "seconds": monotonic() - started}),
          flush=True)
    return result


def groups(*args):
    global processed
    yield from original_groups(*args)
    processed += 1
    if processed % 250 == 0:
        print(snapshot.canonical({"phase": "groups", "assets": processed,
                                  "seconds": monotonic() - started}), flush=True)


original_execute = snapshot_cli.execute


def execute(*args, **kwargs):
    try:
        return original_execute(*args, **kwargs)
    except Exception as error:
        print(snapshot.canonical({"error": type(error).__name__, "frames": [
            [Path(frame.filename).name, frame.lineno]
            for frame in traceback.extract_tb(error.__traceback__)
        ]}), flush=True)
        raise


snapshot._read, snapshot._groups = read, groups
snapshot_cli.execute = execute
snapshot_cli.create_engine = lambda url: engine
sys.argv = ["snapshot", "--selection", str(selection), "--output", str(root / "snapshot"),
            "--code-version", version]
print(snapshot.canonical({"phase": "start", "root": str(root), "code_version": version}),
      flush=True)
try:
    result = snapshot_cli.main()
finally:
    engine.dispose()
if result:
    raise SystemExit(result)
manifest = json.loads((root / "snapshot/manifest.json").read_text())
snapshot.verify(root / "snapshot", manifest["snapshot_id"])
for path in [*root.rglob("*"), root]:
    os.chown(path, account.pw_uid, account.pw_gid)
print(snapshot.canonical({"phase": "verified", "root": str(root),
                          "snapshot_id": manifest["snapshot_id"]}), flush=True)
with (base / "snapshot-success.txt").open("x", encoding="utf-8") as stream:
    stream.write(str(root) + "\n")
