#!/usr/bin/env bash
set -euo pipefail
root=$1
cd "$root/code"
pg=/tmp/colorstats-issue89/pgpkg/root/usr/lib/postgresql/16/bin
export LD_LIBRARY_PATH=/tmp/colorstats-issue89/pgpkg/root/usr/lib/x86_64-linux-gnu
pgroot=$(mktemp -d /tmp/colorstats-issue91-pg-XXXXXX)
mkdir "$pgroot/socket"
"$pg/initdb" -D "$pgroot/pgdata" --auth=trust --no-locale -E UTF8 > "$pgroot/initdb.log"
"$pg/pg_ctl" -D "$pgroot/pgdata" -l "$pgroot/postgres.log" -o "-k $pgroot/socket -p 56191 -h ''" start
trap '"$pg/pg_ctl" -D "$pgroot/pgdata" -m fast stop' EXIT
export PYTHONPATH="$root/code/src:$root/code:/tmp/colorstats-issue89/venv/lib/python3.12/site-packages"
echo "$pgroot" > "$root/pgroot.txt"
for mode in serial parallel; do
  "$pg/createdb" -h "$pgroot/socket" -p 56191 "issue91_$mode"
  export DATABASE_URL="postgresql+psycopg://toumokorosi@/issue91_$mode?host=$pgroot/socket&port=56191"
  /tmp/colorstats-issue90/venv/bin/python bench/issue91/compare.py "$root" "$mode"
done
