#!/bin/bash
set -euo pipefail

bash -n /tmp/colorstats-backup.sh
sudo install -o root -g root -m 755 /tmp/colorstats-backup.sh /usr/local/sbin/colorstats-backup
printf '%s\n' 'colorstats-backup@192.168.1.46:.' | sudo tee /etc/colorstats/backup-destinations >/dev/null
sudo systemctl daemon-reload
sudo rm -f /tmp/colorstats-backup.sh
