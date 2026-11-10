#!/bin/bash
# 新しい完全バックアップを取り、既存DB・保存済みdumpは変更しない。
set -euo pipefail
umask 077
root=${1:?専用バックアップ保存先が必要です}
test ! -e "$root"
mkdir -m 700 -p "$root"
runuser -u postgres -- psql -At -d colorstats -c 'SELECT version_num FROM alembic_version' > "$root/revision-before.txt"
runuser -u postgres -- pg_dump -Fc -d colorstats > "$root/before.dump"
pg_restore --list "$root/before.dump" > "$root/before.dump.list"
sha256sum "$root/before.dump" > "$root/before.dump.sha256"
sha256sum -c "$root/before.dump.sha256"
runuser -u postgres -- psql -At -d colorstats -c 'SELECT version_num FROM alembic_version' > "$root/revision-after.txt"
cmp "$root/revision-before.txt" "$root/revision-after.txt"
test "$(cat "$root/revision-before.txt")" = 0009
wc -c "$root/before.dump"
cat "$root/revision-after.txt"
