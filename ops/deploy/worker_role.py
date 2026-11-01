"""ubuntu-2でSCRAM検証子から専用ロールを新規作成する。平文パスワードは受け取らない。"""

import re
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    verifier = Path(sys.argv[1]).read_text().strip()
    if not re.fullmatch(
        r"SCRAM-SHA-256\$4096:[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+", verifier
    ):
        raise ValueError("SCRAM-SHA-256検証子が必要です")
    grants = Path(__file__).with_name("worker_grants.sql").read_text(encoding="utf-8")
    sql = f"""
BEGIN;
CREATE ROLE colorstats_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE colorstats_worker PASSWORD '{verifier}';
GRANT CONNECT ON DATABASE colorstats TO colorstats_worker;
{grants}
COMMIT;
"""
    subprocess.run(
        ["sudo", "-n", "-u", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-d", "colorstats"],
        input=sql, text=True, check=True,
    )
