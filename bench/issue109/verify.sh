#!/usr/bin/env bash
set -euo pipefail
root=$(mktemp -d /tmp/colorstats-issue109-XXXXXX)
echo "$root"
mkdir "$root/code"
cp -a /mnt/h/mc-blueprint/worktrees/colorstats-109/mc-blueprint-color-stats/. "$root/code/"
cd "$root/code"
python3 - <<'PY'
from pathlib import Path
import subprocess
path = Path('../install-check.sh')
path.write_text(Path('ops/deploy/install.sh').read_text())
subprocess.run(['bash', '-n', str(path)], check=True)
PY
python=/tmp/colorstats-issue89/venv/bin/python
pg=/usr/lib/postgresql/16/bin
mkdir "$root/pgdata" "$root/socket"
chmod 755 "$root"
chown postgres:postgres "$root/pgdata" "$root/socket"
runuser -u postgres -- "$pg/initdb" -D "$root/pgdata" --auth=trust --no-locale -E UTF8 > "$root/initdb.log"
runuser -u postgres -- "$pg/pg_ctl" -D "$root/pgdata" -l "$root/pgdata/postgres.log" -o "-k $root/socket -p 56109 -h ''" start
trap 'runuser -u postgres -- "$pg/pg_ctl" -D "$root/pgdata" -m fast stop' EXIT
runuser -u postgres -- "$pg/createdb" -h "$root/socket" -p 56109 issue109
export TEST_DATABASE_URL="postgresql+psycopg://postgres@/issue109?host=$root/socket&port=56109"
export PYTHONPATH="$root/code/src"
"$python" -m ruff check . > "$root/ruff.log" 2>&1
"$python" -m pytest -q --tb=short "$@" > "$root/pytest.log" 2>&1
tail -30 "$root/pytest.log"
python3 -m venv "$root/build-env"
"$root/build-env/bin/python" -m pip install build hatchling > "$root/build-install.log" 2>&1
"$root/build-env/bin/python" -m build --no-isolation > "$root/build.log" 2>&1
tail -5 "$root/build.log"
