#!/bin/bash
set -euo pipefail

bash -n /tmp/colorstats-backup.sh
sudo install -o root -g root -m 755 /tmp/colorstats-backup.sh /usr/local/sbin/colorstats-backup
sudo install -o root -g root -m 644 /tmp/destinations.example /etc/colorstats/backup-destinations
if ! sudo grep -q '^DATA_ROOT=' /etc/colorstats/backup.conf; then
    printf '%s\n' 'DATA_ROOT=/mnt/data/backup-inputs' | sudo tee -a /etc/colorstats/backup.conf >/dev/null
fi
sudo install -d -o postgres -g postgres -m 700 /mnt/data/backup-inputs /mnt/data/backup-inputs/ground-truth /mnt/data/backup-inputs/aggregates
sudo systemctl daemon-reload
sudo rm -f /tmp/colorstats-backup.sh /tmp/destinations.example
