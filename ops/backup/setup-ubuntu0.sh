#!/bin/bash
set -euo pipefail

uuid=3f9a319f-394c-4cca-805d-fc88d782d644
mountpoint=/srv/colorstats/backup-wd750
device="UUID=$uuid"
test "$(sudo blkid -s UUID -o value "/dev/disk/by-uuid/$uuid")" = "$uuid"
sudo install -d -o root -g root -m 755 "$mountpoint"
if ! sudo grep -Fq "$device $mountpoint ext4" /etc/fstab; then
    printf '%s %s ext4 defaults,nofail 0 2\n' "$device" "$mountpoint" | sudo tee -a /etc/fstab >/dev/null
fi
if ! mountpoint -q "$mountpoint"; then
    sudo mount "$mountpoint"
fi
test "$(findmnt -n -o UUID --target "$mountpoint")" = "$uuid"
sudo chown root:root "$mountpoint"
sudo chmod 755 "$mountpoint"

if ! id colorstats-backup >/dev/null 2>&1; then
    sudo useradd --system --home-dir /var/lib/colorstats-backup --create-home --shell /bin/bash colorstats-backup
fi
sudo install -d -o colorstats-backup -g colorstats-backup -m 700 /var/lib/colorstats-backup/.ssh
sudo install -d -o colorstats-backup -g colorstats-backup -m 700 "$mountpoint/daily" "$mountpoint/weekly"
sudo touch /var/lib/colorstats-backup/.ssh/authorized_keys
sudo chown colorstats-backup:colorstats-backup /var/lib/colorstats-backup/.ssh/authorized_keys
sudo chmod 600 /var/lib/colorstats-backup/.ssh/authorized_keys
sudo chown colorstats-backup:colorstats-backup /var/lib/colorstats-backup
sudo chmod 700 /var/lib/colorstats-backup
