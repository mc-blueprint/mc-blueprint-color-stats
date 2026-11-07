#!/bin/bash

# Issue #120専用の隔離DB検証。
set -euo pipefail

root=$(mktemp -d /tmp/colorstats-issue120-XXXXXX)
chmod 755 "$root"
mkdir -p "$root/code" "$root/socket" "$root/pgdata"

tar -C /mnt/h/mc-blueprint/worktrees/colorstats-120/mc-blueprint-color-stats \
    --exclude=.git --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache \
    --exclude=.ruff_cache --exclude=dist --exclude=data -cf - . | tar -C "$root/code" -xf -
chown postgres:postgres "$root/pgdata" "$root/socket"
pg=/usr/lib/postgresql/16/bin
runuser -u postgres -- "$pg/initdb" -D "$root/pgdata" -A trust > "$root/initdb.log"
runuser -u postgres -- "$pg/pg_ctl" -D "$root/pgdata" -l "$root/pgdata/server.log" \
    -o "-k $root/socket -p 55120 -h ''" start
trap 'runuser -u postgres -- "$pg/pg_ctl" -D "$root/pgdata" stop -m fast' EXIT
"$pg/createdb" -h "$root/socket" -p 55120 -U postgres issue120

cd "$root/code"
venv=/tmp/colorstats-issue87/scratchpad/integrated-venv
export PYTHONPATH="$root/code/src:$root/code"
export TEST_DATABASE_URL="postgresql+psycopg://postgres@/issue120?host=$root/socket&port=55120"

echo "artifact: $root"
"$venv/bin/ruff" check .
"$venv/bin/python" -m pytest -q --tb=short --junitxml="$root/results.xml" "$@"
PYTHONPATH="/tmp/colorstats-issue88/builddeps:$PYTHONPATH" \
    "$venv/bin/python" -m hatchling build -d "$root/dist"
