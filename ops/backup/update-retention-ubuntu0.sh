#!/bin/bash
set -euo pipefail

sudo install -o colorstats-backup -g colorstats-backup -m 644 /tmp/retention.py /var/lib/colorstats-backup/retention.py
sudo install -o root -g root -m 755 /tmp/retention.sh /usr/local/sbin/colorstats-backup-retention
sudo install -o root -g root -m 644 /tmp/colorstats-backup-retention.service /etc/systemd/system/colorstats-backup-retention.service
sudo rm -f /tmp/retention.py
sudo rm -f /tmp/retention.sh /tmp/colorstats-backup-retention.service
sudo systemctl daemon-reload
sudo systemctl start colorstats-backup-retention.service
systemctl show colorstats-backup-retention.service -p Result -p ExecMainStatus
