#!/bin/bash
set -euo pipefail
root=/tmp/colorstats-issue94
mkdir -p "$root/code" "$root/socket" "$root/pgdata"
tar -C /mnt/h/mc-blueprint/worktrees/colorstats-94/mc-blueprint-color-stats \
    --exclude=.git --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache \
    --exclude=.ruff_cache --exclude=dist -cf - . | tar -C "$root/code" -xf -
chown postgres:postgres "$root/pgdata" "$root/socket"
pg=/usr/lib/postgresql/16/bin
if [[ ! -f "$root/pgdata/PG_VERSION" ]]; then
    runuser -u postgres -- "$pg/initdb" -D "$root/pgdata" -A trust > "$root/initdb.log"
fi
runuser -u postgres -- "$pg/pg_ctl" -D "$root/pgdata" -l "$root/pgdata/server.log" \
    -o "-k $root/socket -p 55994 -h ''" start
trap 'runuser -u postgres -- "$pg/pg_ctl" -D "$root/pgdata" stop -m fast' EXIT
database=issue94_$(date +%s)_$$
"$pg/createdb" -h "$root/socket" -p 55994 -U postgres "$database"
cd "$root/code"
venv=/tmp/colorstats-issue87/scratchpad/integrated-venv
export PYTHONPATH="$root/code/src:$root/code"
export TEST_DATABASE_URL="postgresql+psycopg://postgres@/$database?host=$root/socket&port=55994"
"$venv/bin/ruff" check .
"$venv/bin/python" -m pytest -q --tb=short --junitxml="$root/results.xml" "$@"
PYTHONPATH="/tmp/colorstats-issue88/builddeps:$PYTHONPATH" \
    "$venv/bin/python" -m hatchling build -d "$root/dist"
