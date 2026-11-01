#!/bin/bash
set -euo pipefail

key=/var/lib/postgresql/.ssh/colorstats_backup_ed25519
sudo test -s "$key"
test -s /tmp/ubuntu0-hostkey.pub
host_key=$(tr -d '\r' </tmp/ubuntu0-hostkey.pub)
known_hosts=/var/lib/postgresql/.ssh/known_hosts
entry="192.168.1.46 $host_key"
if sudo test -f "$known_hosts"; then
    sudo sed -i 's/\r$//' "$known_hosts"
fi
if ! sudo grep -Fqx -- "$entry" "$known_hosts" 2>/dev/null; then
    printf '%s\n' "$entry" | sudo tee -a "$known_hosts" >/dev/null
fi
sudo chown postgres:postgres "$known_hosts"
sudo chmod 600 "$known_hosts"

sudo install -o root -g root -m 755 /tmp/colorstats-backup.sh /usr/local/sbin/colorstats-backup
sudo install -o root -g root -m 644 /tmp/colorstats-backup.service /etc/systemd/system/colorstats-backup.service
sudo install -o root -g root -m 644 /tmp/colorstats-backup.timer /etc/systemd/system/colorstats-backup.timer
sudo install -d -o root -g root -m 755 /etc/colorstats
printf '%s\n' 'DESTINATIONS_FILE=/etc/colorstats/backup-destinations' | sudo tee /etc/colorstats/backup.conf >/dev/null
printf '%s\n' 'colorstats-backup@192.168.1.46:.' | sudo tee /etc/colorstats/backup-destinations >/dev/null
sudo chmod 644 /etc/colorstats/backup.conf /etc/colorstats/backup-destinations
sudo install -d -o postgres -g postgres -m 700 /var/lib/colorstats-backup
sudo rm -f /tmp/ubuntu0-hostkey.pub /tmp/colorstats-backup.sh /tmp/colorstats-backup.service /tmp/colorstats-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now colorstats-backup.timer
