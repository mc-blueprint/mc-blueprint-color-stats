#!/bin/bash
# WSL root専用。既存DBに接続せず、終了時に今回起動したDBだけを停止する。
set -euo pipefail
root=$(mktemp -d /tmp/colorstats-issue130-XXXXXX)
chmod 755 "$root"
mkdir -p "$root/code" "$root/socket" "$root/pgdata"
tar -C /mnt/h/mc-blueprint/worktrees/colorstats-130/mc-blueprint-color-stats \
    --exclude=.git --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache \
    --exclude=.ruff_cache --exclude=dist --exclude=data -cf - . | tar -C "$root/code" -xf -
chown postgres:postgres "$root/pgdata" "$root/socket"
pg=/usr/lib/postgresql/16/bin
runuser -u postgres -- "$pg/initdb" -D "$root/pgdata" -A trust > "$root/initdb.log"
runuser -u postgres -- "$pg/pg_ctl" -D "$root/pgdata" -l "$root/pgdata/server.log" \
    -o "-k $root/socket -p 55130 -h ''" start
trap 'runuser -u postgres -- "$pg/pg_ctl" -D "$root/pgdata" stop -m fast' EXIT
"$pg/createdb" -h "$root/socket" -p 55130 -U postgres issue130
cd "$root/code"
uv=/opt/colorstats/venvs/issue41/bin/uv
export UV_PROJECT_ENVIRONMENT="$root/venv"
export PYTHONPATH="$root/code/src:$root/code"
export TEST_DATABASE_URL="postgresql+psycopg://postgres@/issue130?host=$root/socket&port=55130"
echo "artifact: $root"
"$uv" sync --frozen --offline > "$root/sync.log" 2>&1
"$root/venv/bin/ruff" check .
"$root/venv/bin/python" -m pytest -q --tb=short --junitxml="$root/results.xml" "$@"
"$uv" build --offline --out-dir "$root/dist"
