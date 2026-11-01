#!/bin/bash
set -euo pipefail

source /etc/colorstats/backup.conf
date_utc=$(date -u +%F)
dump_dir=/var/lib/colorstats-backup
key=/var/lib/postgresql/.ssh/colorstats_backup_ed25519
declare -a artifacts=()
cleanup() {
    if [[ "${KEEP_LOCAL_BACKUP:-0}" != 1 ]]; then
        for artifact in "${artifacts[@]}"; do
            rm -f "$artifact"
        done
    fi
}
trap cleanup EXIT
[[ -s "$DESTINATIONS_FILE" ]]
mkdir -p "$dump_dir"
mapfile -t databases < <(psql -d postgres -Atqc "SELECT datname FROM pg_database WHERE datallowconn AND NOT datistemplate ORDER BY datname")
(( ${#databases[@]} > 0 ))
for database in "${databases[@]}"; do
    [[ "$database" =~ ^[A-Za-z0-9_-]+$ ]]
    dump="${dump_dir}/${database}-${date_utc}.dump"
    artifacts+=("$dump" "${dump}.sha256")
    pg_dump --format=custom --dbname="$database" --file="$dump"
    pg_restore --list "$dump" >/dev/null
    sha256sum "$dump" >"${dump}.sha256"
done

transferred=false
while IFS= read -r destination; do
    [[ -z "$destination" || "$destination" == \#* ]] && continue
    host=${destination%%:*}
    path=${destination#*:}
    [[ "$host" =~ ^[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+$ && ( "$path" == . || ( "$path" == /* && "$path" != *"'"* ) ) ]]
    transferred=true
    rsync -t -e "ssh -i $key -o BatchMode=yes -o StrictHostKeyChecking=yes" "${artifacts[@]}" "${host}:${path}/daily/"
    if [[ "$(date +%u)" == 7 ]]; then
        rsync -t -e "ssh -i $key -o BatchMode=yes -o StrictHostKeyChecking=yes" "${artifacts[@]}" "${host}:${path}/weekly/"
    fi
done < "$DESTINATIONS_FILE"
[[ "$transferred" == true ]]
