#!/bin/bash
set -euo pipefail

sudo install -o colorstats-backup -g colorstats-backup -m 644 /tmp/retention.py /var/lib/colorstats-backup/retention.py
sudo rm -f /tmp/retention.py
sudo systemctl daemon-reload
sudo systemctl start colorstats-backup-retention.service
systemctl show colorstats-backup-retention.service -p Result -p ExecMainStatus
