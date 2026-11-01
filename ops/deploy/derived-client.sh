#!/bin/bash
# ubuntu-1で実行。承認済みのderived共有だけをfstabへ登録する。
set -euo pipefail
test "$(hostname)" = ubuntu-1
sudo -n apt-get install -y nfs-common
sudo -n install -d /mnt/data/derived
entry='192.168.1.86:/mnt/data/derived /mnt/data/derived nfs vers=4.2,proto=tcp,rw,soft,timeo=50,retrans=2,nosuid,nodev,_netdev,nofail 0 0'
if ! grep -Fxq "$entry" /etc/fstab; then
    if findmnt --fstab --mountpoint /mnt/data/derived >/dev/null; then
        echo 'derivedの既存fstab設定を確認してください' >&2
        exit 1
    fi
    printf '%s\n' "$entry" | sudo -n tee -a /etc/fstab >/dev/null
fi
sudo -n systemctl daemon-reload
sudo -n mount /mnt/data/derived
findmnt /mnt/data/derived
probe=$(mktemp /mnt/data/derived/.pilot-write-XXXXXX)
trap 'rm -f -- "$probe"' EXIT
printf 'issue27 NFS write probe\n' > "$probe"
cat "$probe"
