#!/bin/bash
# Ubuntu-24.04の隔離DBで全検証し、終了時に自分のDBだけを停止する。
set -euo pipefail
issue=${COLORSTATS_VERIFY_ISSUE:-122}
source=${COLORSTATS_VERIFY_WORKTREE:-/mnt/h/mc-blueprint/worktrees/colorstats-122/mc-blueprint-color-stats}
port=${COLORSTATS_VERIFY_PORT:-55122}
root=$(mktemp -d "/var/tmp/colorstats-issue${issue}-XXXXXX")
chmod 755 "$root"
mkdir -p "$root/code" "$root/socket" "$root/pgdata"
tar -C "$source" \
    --exclude=.git --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache \
    --exclude=.ruff_cache --exclude=dist --exclude=data -cf - . | tar -C "$root/code" -xf -
chown postgres:postgres "$root/pgdata" "$root/socket"
pg=/usr/lib/postgresql/16/bin
runuser -u postgres -- "$pg/initdb" -D "$root/pgdata" -A trust > "$root/initdb.log"
runuser -u postgres -- "$pg/pg_ctl" -D "$root/pgdata" -l "$root/pgdata/server.log" \
    -o "-k $root/socket -p $port -h ''" start
trap 'runuser -u postgres -- "$pg/pg_ctl" -D "$root/pgdata" stop -m fast' EXIT
"$pg/createdb" -h "$root/socket" -p "$port" -U postgres "issue$issue"
cd "$root/code"
venv=/var/tmp/colorstats-issue121-human-venv
export PYTHONPATH="$root/code/src:$root/code"
export TEST_DATABASE_URL="postgresql+psycopg://postgres@/issue$issue?host=$root/socket&port=$port"
echo "artifact: $root"
"$venv/bin/ruff" check .
"$venv/bin/python" -m pytest -q --tb=short --junitxml="$root/results.xml" "$@"
"$venv/bin/python" -m hatchling build -d "$root/dist"
