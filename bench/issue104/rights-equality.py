"""根拠URLの訂正前後で統計全体・色データ・旧登録行の不変を照合する。"""

import json
import runpy
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from colorstats.stats.snapshot import canonical, digest, verify

root = Path(sys.argv[1])
code = Path(__file__).resolve().parents[2]
previous = Path("/mnt/data/derived/stats/issue104-full-20261105T075242Z")
old = verify(previous / "snapshot",
             "fb7bc1af34b036cb111ae9ae6274195931e2c2271d764eb040e96bda55326942")
new_id = json.loads((root / "snapshot/manifest.json").read_text())["snapshot_id"]
new = verify(root / "snapshot", new_id)
for key in ("selection", "counts", "exclusions", "quality", "config_hash"):
    assert old[key] == new[key], key
changed = sorted(name for name in old["files"] if old["files"][name] != new["files"][name])
assert changed == ["assets.parquet", "provenance.parquet"], changed
old_data = json.loads((previous / "aggregate/dry-1.json").read_text())
new_data = json.loads((root / "aggregate/dry-1.json").read_text())


def without_snapshot_ids(data):
    return data | {"snapshot_id": None, "rows": [
        row | {"quality": row["quality"] | {"snapshot_id": None}} for row in data["rows"]
    ]}


old_values, new_values = without_snapshot_ids(old_data), without_snapshot_ids(new_data)
assert old_values == new_values
old_registration = json.loads((previous / "aggregate/registration.json").read_text())
new_registration = json.loads((root / "aggregate/registration.json").read_text())
row_hash = digest(sorted(new_data["rows"], key=canonical))
old_row_hash = digest(sorted(old_data["rows"], key=canonical))
assert old_row_hash == old_registration["registered_result_hash"]
assert row_hash == new_registration["registered_result_hash"]
audit = runpy.run_path(str(code / "bench/issue75/production.py"))["audit"]
engine = create_engine(URL.create("postgresql+psycopg", database="colorstats"),
                       connect_args={"options": "-c default_transaction_read_only=on"})
try:
    old_db = audit(engine, UUID(old_registration["job_id"]), old_data)
finally:
    engine.dispose()
verify(Path("/mnt/data/derived/stats/issue74-full-20261104T180829Z/snapshot"),
       "3e785e67c42f02a174c85a6f54e2c081447c8c784c912ee3b4c5e7a94cb45702")
result = {
    "previous_snapshot_id": old["snapshot_id"], "replacement_snapshot_id": new_id,
    "previous_run_id": old_registration["run_id"],
    "replacement_run_id": new_registration["run_id"],
    "changed_parquet_files": changed,
    "unchanged_parquet_files": sorted(set(old["files"]) - set(changed)),
    "full_statistics_equal_except_snapshot_id": True, "rows_equal": len(new_data["rows"]),
    "ignored_identifier_fields": ["snapshot_id", "rows[].quality.snapshot_id"],
    "statistical_values_hash": digest(new_values),
    "previous_registered_rows_hash": old_row_hash, "registered_rows_hash": row_hash,
    "previous_run_audit": old_db,
    "previous_snapshot_verified": True, "old_m3_snapshot_verified": True,
}
with (root / "rights-statistics-equality.json").open("x", encoding="utf-8") as stream:
    stream.write(canonical(result) + "\n")
print(canonical(result))
