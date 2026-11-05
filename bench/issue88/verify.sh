#!/bin/bash
set -euo pipefail
root=/tmp/colorstats-issue88
mkdir -p "$root/code" "$root/socket" "$root/data"
tar -C /mnt/h/mc-blueprint/worktrees/colorstats-88/mc-blueprint-color-stats \
    --exclude=.git --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache \
    --exclude=.ruff_cache --exclude=dist -cf - . | tar -C "$root/code" -xf -
chown postgres:postgres "$root/data" "$root/socket"
pg=/usr/lib/postgresql/16/bin
if [[ ! -f "$root/data/PG_VERSION" ]]; then
    runuser -u postgres -- "$pg/initdb" -D "$root/data" -A trust >/dev/null
fi
runuser -u postgres -- "$pg/pg_ctl" -D "$root/data" -l "$root/data/server.log" \
    -o "-k $root/socket -p 55888 -h ''" start
trap 'runuser -u postgres -- "$pg/pg_ctl" -D "$root/data" stop -m fast' EXIT
database=colorstats88_$(date +%s)_$$
"$pg/createdb" -h "$root/socket" -p 55888 -U postgres "$database"
cd "$root/code"
venv=/tmp/colorstats-issue87/scratchpad/integrated-venv
export PYTHONPATH="$root/code/src:$root/code"
export TEST_DATABASE_URL="postgresql+psycopg://postgres@/$database?host=$root/socket&port=55888"
"$venv/bin/ruff" check .
"$venv/bin/python" -m pytest -q --junitxml="$root/results.xml" "$@"
PYTHONPATH="$root/builddeps:$PYTHONPATH" "$venv/bin/python" -m hatchling build -d "$root/dist"
