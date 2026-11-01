#!/bin/bash
# ubuntu-2で実行。共有方式の承認後にだけ適用する。
set -euo pipefail
test "$(hostname)" = ubuntu-2
sudo -n apt-get install -y nfs-kernel-server
sudo -n install -d -o toumokorosi -g toumokorosi /mnt/data/derived
sudo -n install -d /etc/exports.d
printf '%s\n' '/mnt/data/derived 192.168.1.85(rw,sync,no_subtree_check,root_squash)' |
    sudo -n tee /etc/exports.d/colorstats-pilot.exports >/dev/null
sudo -n exportfs -ra
sudo -n systemctl start nfs-server
sudo -n exportfs -v
