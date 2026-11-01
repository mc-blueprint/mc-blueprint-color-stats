#!/bin/bash
set -euo pipefail

key=/var/lib/postgresql/.ssh/colorstats_backup_ed25519
sudo -u postgres install -d -m 700 /var/lib/postgresql/.ssh
if ! sudo test -s "$key"; then
    sudo -u postgres ssh-keygen -q -t ed25519 -N '' -f "$key"
fi
sudo cat "${key}.pub"
