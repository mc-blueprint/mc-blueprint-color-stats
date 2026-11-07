#!/bin/bash
set -euo pipefail
host=$1
release=$2
batch=/mnt/data/derived/issue114-batch1-20261106
export PYTHONPATH="$release/src:$release"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
cd "$release"
trap 'touch "$batch/$host.failed"' ERR
if [ "$host" = ubuntu1 ]; then
    python=/opt/colorstats/work/issue66-20261104/.venv/bin/python
    models=/opt/colorstats/work/issue66-20261104/models
    while systemctl is-active --quiet colorstats-issue114-batch1-collect-resume; do sleep 30; done
    "$python" - "$batch" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
result=json.loads((root/'collection.json').read_text())
assert not result['reason'].startswith('failed:') and result['worker_exit']==0
assert len(json.loads((root/'new-assets.json').read_text())) >= 2
PY
    "$python" ops/deploy/launch.py -m bench.issue114.batch1 prep --root "$batch" \
        --code-version 49f4282
    "$python" - "$batch" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
rows=json.loads((root/'prep-report.json').read_text())
assert all(row['status'] in ('succeeded','failed') for row in rows)
PY
    touch "$batch/prep.done"
else
    python=/mnt/data/work/issue-40/venv/bin/python
    models=/mnt/data/work/issue-40/models
    while [ ! -e "$batch/prep.done" ]; do
        test ! -e "$batch/ubuntu1.failed"
        sleep 30
    done
fi
"$python" - "$batch" "$host" <<'PY'
import json,sys
from pathlib import Path
root,host=Path(sys.argv[1]),sys.argv[2]
assert json.loads((root/'models-ubuntu1.json').read_text()) == json.loads(
    (root/'models-ubuntu2.json').read_text())
identifiers=sorted(json.loads((root/'new-assets.json').read_text()))
cut=max(1,len(identifiers)*2//5)
first,second=identifiers[:cut],identifiers[cut:]
assert first and second and not set(first)&set(second)
assert sorted(first+second)==identifiers
with (root/(host+'-assets.json')).open('x') as stream:
    json.dump(first if host=='ubuntu1' else second,stream)
PY
runner() {
    if [ "$host" = ubuntu1 ]; then
        "$python" ops/deploy/launch.py -m ops.deploy.m3_analysis "$@"
    else
        "$python" /mnt/data/work/issue-66/peer.py "$@"
    fi
}
test -z "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader)"
runner freeze --root "$batch/$host" --asset-ids "$batch/$host-assets.json"
runner run --root "$batch/$host" --models "$models" --limit 3
runner report --root "$batch/$host" --output "$batch/$host/smoke-report.json"
"$python" - "$batch/$host/smoke-report.json" "$batch/$host-assets.json" <<'PY'
import json,sys
from bench.issue114.batch1 import check_analysis
result=json.load(open(sys.argv[1]))
check_analysis(result,len(json.load(open(sys.argv[2]))),limit=3)
PY
runner run --root "$batch/$host" --models "$models"
runner report --root "$batch/$host" --output "$batch/$host/report.json"
"$python" - "$batch/$host/report.json" "$batch/$host-assets.json" <<'PY'
import json,sys
from bench.issue114.batch1 import check_analysis
check_analysis(json.load(open(sys.argv[1])),len(json.load(open(sys.argv[2]))))
PY
touch "$batch/$host.done"
