#!/usr/bin/env bash
set -euo pipefail
root=/tmp/colorstats-issue90
if [[ ! -x "$root/venv/bin/python" ]]; then
    python3 -m venv "$root/venv"
    "$root/venv/bin/python" -m pip install --no-deps \
        "$root/mc_blueprint_color_stats-0.1.0-py3-none-any.whl"
    "$root/venv/bin/python" - <<'PY'
from pathlib import Path
import site
Path(site.getsitepackages()[0], 'issue90-test-dependencies.pth').write_text(
    '/tmp/colorstats-issue90/testdeps\n'
    '/tmp/colorstats-issue89/venv/lib/python3.12/site-packages\n'
    '/opt/colorstats/venvs/gpucheck/lib/python3.12/site-packages\n'
)
PY
fi
pg=/tmp/colorstats-issue89/pgpkg/root/usr/lib/postgresql/16/bin
export LD_LIBRARY_PATH=/tmp/colorstats-issue89/pgpkg/root/usr/lib/x86_64-linux-gnu
mkdir -p "$root/socket"
if [[ ! -f "$root/pgdata/PG_VERSION" ]]; then
    "$pg/initdb" -D "$root/pgdata" --auth=trust --no-locale -E UTF8 > "$root/initdb.log"
fi
"$pg/pg_ctl" -D "$root/pgdata" -l "$root/postgres.log" -o "-k $root/socket -p 55990 -h ''" start
trap '"$pg/pg_ctl" -D "$root/pgdata" -m fast stop' EXIT
database_name="issue90_$(date -u +%Y%m%d%H%M%S)"
"$pg/createdb" -h "$root/socket" -p 55990 "$database_name"
export TEST_DATABASE_URL="postgresql+psycopg://toumokorosi@/$database_name?host=$root/socket&port=55990"
export PYTHONPATH="src:$root/testdeps:/tmp/colorstats-issue89/venv/lib/python3.12/site-packages"
if [[ $# == 0 ]]; then
    set -- tests
fi
"$root/venv/bin/python" -m pytest "$@" -q --tb=short > "$root/db-tests.log" 2>&1
tail -25 "$root/db-tests.log"
