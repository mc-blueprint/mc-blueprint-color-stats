#!/bin/bash
set -euo pipefail

for entry in \
    'backup-wd750 3f9a319f-394c-4cca-805d-fc88d782d644' \
    'backup-st500a 71cefe86-d90a-4caa-be51-54cc5f8d6ebc' \
    'backup-st500b e53f78c3-2918-4a64-bc50-807a38249da1'; do
    read -r name uuid <<< "$entry"
    root="/srv/colorstats/$name"
    for period in daily weekly; do
        if ! /usr/bin/python3 /usr/local/lib/colorstats-backup/health.py "$uuid"; then
            break
        fi
        [[ "$(findmnt -n -o UUID --mountpoint "$root")" == "$uuid" ]] || continue
        generations=7
        [[ "$period" == weekly ]] && generations=4
        /usr/bin/python3 /var/lib/colorstats-backup/retention.py \
            "$root/$period" --generations "$generations"
    done
done
