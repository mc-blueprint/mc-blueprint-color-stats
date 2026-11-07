#!/bin/bash
set -euo pipefail
host=$1
release=$2
batch=/mnt/data/derived/issue114-batch1-20261106/auto-v2
export PYTHONPATH="$release/src:$release"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
cd "$release"
trap 'touch "$batch/$host.failed"' ERR
if [ "$host" = ubuntu1 ]; then
    python=/opt/colorstats/work/issue66-20261104/.venv/bin/python
    models=/opt/colorstats/work/issue66-20261104/models
else
    python=/mnt/data/work/issue-40/venv/bin/python
    models=/mnt/data/work/issue-40/models
fi
runner() {
    if [ "$host" = ubuntu1 ]; then
        "$python" ops/deploy/launch.py -m ops.deploy.m3_analysis "$@"
    else
        "$python" /mnt/data/work/issue-66/peer.py "$@"
    fi
}
runner freeze --root "$batch/$host" --asset-ids "$batch/$host-assets.json" --reuse-segments
runner run --root "$batch/$host" --models "$models" --limit 3
runner report --root "$batch/$host" --output "$batch/$host/smoke-report.json"
"$python" - "$batch" "$host" <<'PY'
import json,sys
from pathlib import Path
from bench.issue114.batch1 import check_analysis
root,host=Path(sys.argv[1]),sys.argv[2]
check_analysis(json.loads((root/host/'smoke-report.json').read_text()),
               len(json.loads((root/(host+'-assets.json')).read_text())),limit=3)
PY
touch "$batch/$host.smoke.done"
while [ ! -e "$batch/ubuntu1.smoke.done" ] || [ ! -e "$batch/ubuntu2.smoke.done" ]; do
    test ! -e "$batch/ubuntu1.failed"
    test ! -e "$batch/ubuntu2.failed"
    sleep 30
done
runner run --root "$batch/$host" --models "$models"
runner report --root "$batch/$host" --output "$batch/$host/report.json"
"$python" - "$batch" "$host" <<'PY'
import json,sys
from pathlib import Path
from bench.issue114.batch1 import check_analysis
root,host=Path(sys.argv[1]),sys.argv[2]
check_analysis(json.loads((root/host/'report.json').read_text()),
               len(json.loads((root/(host+'-assets.json')).read_text())))
PY
touch "$batch/$host.done"
