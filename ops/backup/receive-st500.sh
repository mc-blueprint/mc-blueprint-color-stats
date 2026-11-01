#!/bin/bash
set -euo pipefail

mountpoint=$1
uuid=$2
mountpoint -q "$mountpoint"
[[ "$(findmnt -n -o UUID --mountpoint "$mountpoint")" == "$uuid" ]]
if [[ "${SSH_ORIGINAL_COMMAND:-}" == health ]]; then
    exec /usr/bin/python3 /usr/local/lib/colorstats-backup/health.py "$uuid"
fi
/usr/bin/python3 /usr/local/lib/colorstats-backup/health.py "$uuid" >&2
exec /usr/bin/rrsync -wo "$mountpoint"
