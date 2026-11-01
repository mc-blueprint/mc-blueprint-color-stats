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

for name in ground-truth aggregates; do
    archive="${dump_dir}/${name}-${date_utc}.tar.gz"
    artifacts+=("$archive" "${archive}.sha256")
    tar -czf "$archive" -C "$DATA_ROOT" "$name"
    sha256sum "$archive" >"${archive}.sha256"
done

declare -a destinations=()
declare -A uuids=()
excluded=0
while IFS= read -r destination; do
    [[ -z "$destination" || "$destination" == \#* ]] && continue
    host=${destination%%:*}
    path=${destination#*:}
    [[ "$host" =~ ^[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+$ && ( "$path" == . || ( "$path" == /* && "$path" != *"'"* ) ) ]]
    if ! health=$(ssh -n -i "$key" -o BatchMode=yes -o StrictHostKeyChecking=yes "$host" health 2>&1); then
        printf 'excluded destination=%s reason=%s\n' "$destination" "$health"
        excluded=$((excluded + 1))
        continue
    fi
    [[ "$health" =~ ^uuid=([a-fA-F0-9-]+)$ ]]
    uuid=${BASH_REMATCH[1]}
    [[ -n "${uuids[$uuid]:-}" ]] && continue
    uuids[$uuid]=1
    destinations+=("$destination")
done < "$DESTINATIONS_FILE"
printf 'backup destinations: healthy=%s excluded=%s\n' "${#destinations[@]}" "$excluded"
if (( ${#destinations[@]} < 2 )); then
    echo 'backup failed: fewer than 2 healthy media' >&2
    exit 1
fi
for destination in "${destinations[@]}"; do
    host=${destination%%:*}
    path=${destination#*:}
    rsync -t -e "ssh -i $key -o BatchMode=yes -o StrictHostKeyChecking=yes" "${artifacts[@]}" "${host}:${path}/daily/"
    if [[ "$(date +%u)" == 7 ]]; then
        rsync -t -e "ssh -i $key -o BatchMode=yes -o StrictHostKeyChecking=yes" "${artifacts[@]}" "${host}:${path}/weekly/"
    fi
    printf 'transferred destination=%s\n' "$destination"
done
printf 'backup result: transferred=%s\n' "${#destinations[@]}"
