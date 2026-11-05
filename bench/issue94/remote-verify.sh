#!/bin/bash
set -euo pipefail
root=/mnt/data/work/issue-94
pg=/tmp/colorstats-issue89/pgpkg/root/usr/lib/postgresql/16/bin
export LD_LIBRARY_PATH=/tmp/colorstats-issue89/pgpkg/root/usr/lib/x86_64-linux-gnu
mkdir -p "$root/socket" "$root/pgdata"
if [[ ! -f "$root/pgdata/PG_VERSION" ]]; then
    "$pg/initdb" -D "$root/pgdata" --auth=trust --no-locale -E UTF8 > "$root/initdb.log"
fi
"$pg/pg_ctl" -D "$root/pgdata" -l "$root/postgres.log" \
    -o "-k $root/socket -p 55994 -h ''" start
trap '"$pg/pg_ctl" -D "$root/pgdata" -m fast stop' EXIT
database_name=issue94_$(date -u +%Y%m%d%H%M%S)
"$pg/createdb" -h "$root/socket" -p 55994 "$database_name"
export TEST_DATABASE_URL="postgresql+psycopg://toumokorosi@/$database_name?host=$root/socket&port=55994"
export PYTHONPATH="src:.:/tmp/colorstats-issue90/testdeps:/tmp/colorstats-issue89/venv/lib/python3.12/site-packages"
/tmp/colorstats-issue90/venv/bin/python -m pytest tests/test_mapillary.py \
    tests/test_mapillary_db.py -q --tb=short --basetemp="$root/fixtures-$database_name"
