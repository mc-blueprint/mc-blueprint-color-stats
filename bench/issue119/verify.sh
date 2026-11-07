#!/usr/bin/env bash
# WSL Ubuntu-24.04 の隔離DBで検証する。本番・共有DBへ接続しない。
set -euo pipefail
cd "$(dirname "$0")/../.."
venv=${COLORSTATS_TEST_VENV:-/tmp/colorstats-117-venv}
export PYTHONPATH="$PWD/src:$PWD"
export PYTHONPYCACHEPREFIX=/tmp/colorstats-119-pycache
root=$(mktemp -d /tmp/colorstats-119-db-XXXXXX)
chmod 755 "$root"
mkdir "$root/pgdata" "$root/socket"
chown postgres:postgres "$root/pgdata" "$root/socket"
pg=/usr/lib/postgresql/16/bin
runuser -u postgres -- "$pg/initdb" -D "$root/pgdata" -A trust > "$root/initdb.log"
trap 'runuser -u postgres -- "$pg/pg_ctl" -D "$root/pgdata" -m fast -w stop' EXIT
runuser -u postgres -- "$pg/pg_ctl" -D "$root/pgdata" -l "$root/pgdata/server.log" \
    -o "-F -k $root/socket -h ''" -w start
runuser -u postgres -- "$pg/createdb" -h "$root/socket" colorstats_test
export TEST_DATABASE_URL="postgresql+psycopg://postgres@/colorstats_test?host=$root/socket"
"$venv/bin/ruff" check .
"$venv/bin/python" -m pytest "${@:-tests}"
PYTHONPATH="${COLORSTATS_BUILD_DEPS:-/tmp/colorstats-issue88/builddeps}:$PYTHONPATH" \
    "$venv/bin/python" -m hatchling build
