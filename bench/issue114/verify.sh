#!/bin/bash
set -euo pipefail
root=$(mktemp -d /tmp/colorstats-issue114-XXXXXX)
chmod 755 "$root"
mkdir -p "$root/code" "$root/socket" "$root/pgdata"
tar -C /mnt/h/mc-blueprint/worktrees/colorstats-114/mc-blueprint-color-stats \
    --exclude=.git --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache \
    --exclude=.ruff_cache --exclude=dist -cf - . | tar -C "$root/code" -xf -
chown postgres:postgres "$root/pgdata" "$root/socket"
pg=/usr/lib/postgresql/16/bin
runuser -u postgres -- "$pg/initdb" -D "$root/pgdata" -A trust > "$root/initdb.log"
runuser -u postgres -- "$pg/pg_ctl" -D "$root/pgdata" -l "$root/pgdata/server.log" \
    -o "-k $root/socket -p 55114 -h ''" start
trap 'runuser -u postgres -- "$pg/pg_ctl" -D "$root/pgdata" stop -m fast' EXIT
"$pg/createdb" -h "$root/socket" -p 55114 -U postgres issue114
cd "$root/code"
venv=/tmp/colorstats-issue87/scratchpad/integrated-venv
export PYTHONPATH="$root/code/src:$root/code"
export TEST_DATABASE_URL="postgresql+psycopg://postgres@/issue114?host=$root/socket&port=55114"
echo "artifact: $root"
"$venv/bin/python" bench/issue114/dry_run.py
"$venv/bin/ruff" check .
"$venv/bin/python" -m pytest -q --tb=short --junitxml="$root/results.xml" "$@"
PYTHONPATH="/tmp/colorstats-issue88/builddeps:$PYTHONPATH" \
    "$venv/bin/python" -m hatchling build -d "$root/dist"
