#!/bin/sh
set -eu
umask 077
mkdir -p /root/.ssh
if [ -n "${PUBLIC_KEY:-}" ]; then
    printf '%s\n' "$PUBLIC_KEY" > /root/.ssh/authorized_keys
fi
if [ ! -s /root/.ssh/authorized_keys ]; then
    printf '%s\n' 'SSH公開鍵の登録が必要です' >&2
    exit 1
fi
ssh-keygen -A
exec /usr/sbin/sshd -D -e -o PasswordAuthentication=no -o PermitRootLogin=prohibit-password
