#!/bin/bash
set -euo pipefail

mountpoint=/srv/colorstats/backup-wd750
uuid=3f9a319f-394c-4cca-805d-fc88d782d644
test "$(findmnt -n -o UUID --target "$mountpoint")" = "$uuid"
sudo install -o colorstats-backup -g colorstats-backup -m 644 /tmp/retention.py /var/lib/colorstats-backup/retention.py
sudo install -o root -g root -m 644 /tmp/colorstats-backup-retention.service /etc/systemd/system/colorstats-backup-retention.service
sudo install -o root -g root -m 644 /tmp/colorstats-backup-retention.timer /etc/systemd/system/colorstats-backup-retention.timer

key=$(cat /tmp/colorstats-backup.pub)
authorized=/var/lib/colorstats-backup/.ssh/authorized_keys
entry="command=\"/usr/local/sbin/colorstats-receive-st500 $mountpoint $uuid\",restrict $key"
if ! sudo grep -Fqx -- "$entry" "$authorized"; then
    printf '%s\n' "$entry" | sudo tee -a "$authorized" >/dev/null
fi
sudo chmod 600 "$authorized"
sudo chown colorstats-backup:colorstats-backup "$authorized"
sudo rm -f /tmp/colorstats-backup.pub /tmp/retention.py /tmp/colorstats-backup-retention.service /tmp/colorstats-backup-retention.timer
sudo systemctl daemon-reload
sudo systemctl enable --now colorstats-backup-retention.timer
