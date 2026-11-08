#!/bin/bash
# ubuntu-2の本番DB全体を新しい私有パスへ保存する。既存dumpは変更しない。
set -euo pipefail
umask 077
root=${1:?第1引数に専用バックアップ保存先を指定してください}
test ! -e "$root/before.dump"
install -d -m 700 "$root"
temporary=$(mktemp -d /var/tmp/colorstats-i129-backup-XXXXXX)
chown postgres:postgres "$temporary"
runuser -u postgres -- pg_dump -Fc -d colorstats -f "$temporary/before.dump"
pg_restore --list "$temporary/before.dump" > "$root/before.dump.list"
install -m 600 "$temporary/before.dump" "$root/before.dump"
python3 - "$root" <<'PY'
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
root = Path(sys.argv[1])
data = {"sha256": hashlib.sha256((root / "before.dump").read_bytes()).hexdigest(),
        "bytes": (root / "before.dump").stat().st_size,
        "at": datetime.now(UTC).isoformat(), "database": "colorstats",
        "host": "ubuntu-2", "format": "pg_dump-custom-full", "toc_verified": True}
(root / "backup.json").write_text(json.dumps(data, indent=2))
print(json.dumps(data))
PY
# 既存#117と同じNFS root-squash後の主体。アクセスmodeは広げない。
chown 65534:65534 "$root" "$root/before.dump" "$root/before.dump.list" "$root/backup.json"
