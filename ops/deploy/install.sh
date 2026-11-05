#!/bin/bash
# 展開済みの固定スナップショットから専用環境を作る。サービスは明示的に起動する。
set -euo pipefail
release=$(realpath "$1")
analysis_version=${2:-$(basename "$release")}
test -f "$release/uv.lock"
sudo -n install -d -m 700 -o toumokorosi -g toumokorosi /var/lib/colorstats/pilot
sudo -n chown -R toumokorosi:toumokorosi "$release"
python3 -m venv "$release/bootstrap"
"$release/bootstrap/bin/pip" --disable-pip-version-check install uv==0.13.6
cd "$release"
"$release/bootstrap/bin/uv" sync --frozen --no-dev --python /usr/bin/python3
if [ ! -e /var/lib/colorstats/pilot/database.json ]; then
    .venv/bin/python ops/deploy/credentials.py /var/lib/colorstats/pilot
fi
test -f /var/lib/colorstats/pilot/targets.yaml || cp configs/collection_targets.yaml /var/lib/colorstats/pilot/targets.yaml
for disk in /srv/colorstats/raw-orico /srv/colorstats/raw-suneast; do
    mountpoint -q "$disk"
    # 既存ファイル・lost+foundには触れず、画像配置に必要な媒体ルートだけを委譲する。
    sudo -n chown toumokorosi:toumokorosi "$disk"
done
for stage in collect analysis scheduler; do
    mounts='/srv/colorstats/raw-orico /srv/colorstats/raw-suneast'
    condition=''
    if [ "$stage" = analysis ]; then
        mounts="$mounts /mnt/data/derived"
        condition='ConditionPathIsMountPoint=/mnt/data/derived'
    fi
    case "$stage" in
        collect) command="-m colorstats.queue --handler collect=colorstats.collect.bias --handler review=colorstats.collect.quality --stop-file /var/lib/colorstats/pilot/collect.stop" ;;
        analysis) command="-m colorstats.queue --handler prep=colorstats.analyze.prep --handler color=colorstats.analyze.color --storage-path prep=/mnt/data/derived --storage-path color=/mnt/data/derived --stop-file /var/lib/colorstats/pilot/analysis.stop" ;;
        scheduler) command="ops/deploy/pilot.py --root $release --state /var/lib/colorstats/pilot --version $(basename "$release") --analysis-version $analysis_version --run" ;;
    esac
    sudo -n tee "/etc/systemd/system/colorstats-pilot-$stage.service" >/dev/null <<EOF
[Unit]
Description=M1 pilot $stage
Wants=network-online.target
After=network-online.target
RequiresMountsFor=$mounts
$condition
ConditionPathExists=!/var/lib/colorstats/pilot/$stage.stop

[Service]
Type=simple
User=toumokorosi
Group=toumokorosi
WorkingDirectory=$release
Environment=OPENBLAS_NUM_THREADS=1
Environment=OMP_NUM_THREADS=1
ExecStart=$release/.venv/bin/python $release/ops/deploy/launch.py $command
ExecStop=$release/.venv/bin/python $release/ops/deploy/stop.py /var/lib/colorstats/pilot/$stage.stop \$MAINPID
KillMode=mixed
TimeoutStopSec=15
Restart=on-failure
RestartSec=30
UMask=0077

[Install]
WantedBy=multi-user.target
EOF
done
sudo -n systemctl daemon-reload
printf 'installed: %s\n' "$release"
