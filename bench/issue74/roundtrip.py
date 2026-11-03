"""固定fixtureのParquetを別OSで読み直し、値を照合して再出力する。"""

import hashlib
import json
import sys
from pathlib import Path
from time import monotonic

import duckdb

from colorstats.stats.snapshot import canonical, digest, verify

source, expected, destination = sys.argv[1:]
source, destination = Path(source), Path(destination)
started = monotonic()
manifest = verify(source, expected)
destination.mkdir(parents=True, exist_ok=False)
with duckdb.connect() as db:
    for name, record in manifest["files"].items():
        origin, target = source / name, destination / name
        db.execute("CREATE OR REPLACE TEMP TABLE copied AS "
                   "SELECT * FROM read_parquet(?) ORDER BY ALL", [str(origin)])
        db.execute("COPY copied TO ? (FORMAT PARQUET)", [str(target)])
        before = db.execute("SELECT * FROM read_parquet(?) ORDER BY ALL", [str(origin)]).fetchall()
        after = db.execute("SELECT * FROM read_parquet(?) ORDER BY ALL", [str(target)]).fetchall()
        assert before == after
        record["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
manifest.pop("snapshot_id")
manifest["roundtrip_source_hash"] = expected
manifest["snapshot_id"] = digest(manifest)
(destination / "manifest.json").write_text(canonical(manifest), encoding="utf-8")
verify(destination, manifest["snapshot_id"])
print(json.dumps({
    "snapshot_id": manifest["snapshot_id"], "tables": len(manifest["files"]),
    "rows": sum(record["rows"] for record in manifest["files"].values()),
    "bytes": sum(path.stat().st_size for path in destination.iterdir()),
    "seconds": round(monotonic() - started, 3),
}))
