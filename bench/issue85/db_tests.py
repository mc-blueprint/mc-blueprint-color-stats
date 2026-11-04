"""#72と同じ専用PostgreSQL 16をソケット限定で起動し、終了時に停止する。"""

import os
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy.engine import URL

ROOT = Path("/mnt/data/work/issue-85/postgres")
BIN = Path("/usr/lib/postgresql/16/bin")


def pg(command, *args):
    subprocess.run([str(BIN / command), *map(str, args)], check=True)


if __name__ == "__main__":
    ROOT.mkdir(exist_ok=True)
    (ROOT / "socket").mkdir(exist_ok=True)
    if not (ROOT / "data/PG_VERSION").exists():
        pg("initdb", "-D", ROOT / "data", "-A", "trust", "--no-locale", "--encoding=UTF8")
    pg("pg_ctl", "-D", ROOT / "data", "-l", ROOT / "server.log",
       "-o", f"-h '' -k {ROOT / 'socket'} -p 5585", "-w", "start")
    try:
        database = "colorstats_test85_" + uuid.uuid4().hex[:12]
        pg("createdb", "-h", ROOT / "socket", "-p", "5585", database)
        os.environ["TEST_DATABASE_URL"] = URL.create(
            "postgresql+psycopg", username="postgres", database=database,
            query={"host": str(ROOT / "socket"), "port": "5585"},
        ).render_as_string(hide_password=False)
        raise SystemExit(pytest.main([
            "-q", "-x", "--tb=short", "-o", f"cache_dir={ROOT / 'pytest-cache'}",
        ]))
    finally:
        pg("pg_ctl", "-D", ROOT / "data", "-m", "fast", "-w", "stop")
