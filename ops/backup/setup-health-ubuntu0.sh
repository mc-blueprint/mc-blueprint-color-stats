#!/bin/bash
set -euo pipefail

sudo install -d -o root -g root -m 755 /usr/local/lib/colorstats-backup
sudo install -o root -g root -m 644 /tmp/health.py /usr/local/lib/colorstats-backup/health.py
sudo install -o root -g root -m 755 /tmp/receive-st500.sh /usr/local/sbin/colorstats-receive-st500
sudo python3 - <<'PY'
from pathlib import Path

authorized = Path('/var/lib/colorstats-backup/.ssh/authorized_keys')
old = 'command="/usr/bin/rrsync -wo /srv/colorstats/backup-wd750",restrict '
new = ('command="/usr/local/sbin/colorstats-receive-st500 '
       '/srv/colorstats/backup-wd750 3f9a319f-394c-4cca-805d-fc88d782d644",restrict ')
lines = authorized.read_text().splitlines()
authorized.write_text(''.join(
    (new + line[len(old):] if line.startswith(old) else line) + '\n' for line in lines
))
PY
