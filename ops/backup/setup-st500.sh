#!/bin/bash
set -euo pipefail

# フォーマット済みの2媒体を登録する。既存ファイルシステムは変更しない。
for entry in 'a 71cefe86-d90a-4caa-be51-54cc5f8d6ebc 9QG4GD0M' 'b e53f78c3-2918-4a64-bc50-807a38249da1 9QG4B26Z'; do
    read -r suffix uuid serial <<< "$entry"
    mount=/srv/colorstats/backup-st500$suffix
    account=colorstats-backup-st500$suffix
    device=$(readlink -f "/dev/disk/by-uuid/$uuid")
    parent=$(lsblk -dn -o PKNAME "$device")
    [[ "$(lsblk -dn -o SERIAL "/dev/$parent")" == "$serial" ]]
    [[ "$(sudo blkid -s TYPE -o value "$device")" == ext4 ]]
    sudo install -d -o root -g root -m 755 "$mount"
    line="UUID=$uuid $mount ext4 defaults,nofail 0 2"
    if ! grep -Fqx "$line" /etc/fstab; then
        printf '%s\n' "$line" | sudo tee -a /etc/fstab >/dev/null
    fi
    if ! mountpoint -q "$mount"; then
        sudo mount "$mount"
    fi
    [[ "$(findmnt -n -o UUID --mountpoint "$mount")" == "$uuid" ]]
    if ! id "$account" >/dev/null 2>&1; then
        sudo useradd --system --create-home --home-dir "/var/lib/$account" --gid colorstats-backup --shell /bin/bash "$account"
    fi
    sudo install -d -o "$account" -g colorstats-backup -m 2770 "$mount/daily" "$mount/weekly"
    sudo install -d -o "$account" -g colorstats-backup -m 700 "/var/lib/$account/.ssh"
    sudo python3 - "$account" "$mount" "$uuid" <<'PY'
import pathlib
import subprocess
import sys

account, mount, uuid = sys.argv[1:]
lines = pathlib.Path('/var/lib/colorstats-backup/.ssh/authorized_keys').read_text().splitlines()
prefix = ('command="/usr/local/sbin/colorstats-receive-st500 '
          '/srv/colorstats/backup-wd750 3f9a319f-394c-4cca-805d-fc88d782d644",restrict ')
keys = [line[len(prefix):] for line in lines if line.startswith(prefix)]
assert keys, '既存WD受信用の公開鍵が必要です'
target = pathlib.Path('/var/lib', account, '.ssh/authorized_keys')
target.write_text(''.join(
    f'command="/usr/local/sbin/colorstats-receive-st500 {mount} {uuid}",restrict {key}\n'
    for key in keys
))
target.chmod(0o600)
subprocess.run(['chown', f'{account}:colorstats-backup', str(target)], check=True)
PY
done
sudo systemctl daemon-reload
