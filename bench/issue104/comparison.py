"""固定した旧版・新版の数値だけを比較し、外部監査をM3判定へ接続する。"""

import copy
import hashlib
import json
import sys
from pathlib import Path

from colorstats.stats.snapshot import canonical, digest

code = Path(__file__).resolve().parents[2]
root = Path(sys.argv[1])
old = json.loads((code / "bench/issue75/full-summary.json").read_text(encoding="utf-8"))
new = json.loads((root / "aggregate/registration.json").read_text(encoding="utf-8"))
old_snapshot = json.loads((code / "bench/issue74/full-summary.json").read_text(encoding="utf-8"))
snapshot = json.loads((root / "snapshot/manifest.json").read_text(encoding="utf-8"))
report = json.loads((root / "report/report.json").read_text(encoding="utf-8"))
audit = json.loads((root / "snapshot-audit.json").read_text(encoding="utf-8"))
prior = json.loads((code / "bench/issue76/m3-assessment.json").read_text(encoding="utf-8"))
old_root = Path("/mnt/data/derived/stats/issue74-full-20261104T180829Z")
assert snapshot["selection"] == json.loads((old_root / "selection.json").read_text())
assert not any(audit["violations"].values())
assert new["database_rows_equal"] and new["duplicate_enqueue_equal"]
assert audit["failed_contributions"] == 0
checks = copy.deepcopy(report["m3_checks"])
for index in (0, 1):
    checks[index] = prior["m3_checks"][index]
    checks[index]["reason"] += (
        " #104も同じコホート・解析run・同定根拠を保持し、元情報hashと全量監査が一致。"
    )
assessment = {
    "snapshot_id": snapshot["snapshot_id"], "statistics_run_id": new["run_id"],
    "report_sha256": hashlib.sha256((root / "report/report.json").read_bytes()).hexdigest(),
    "basis": "条件1・2に既存本番監査と入力不変性を接続。自動reportのバイト列は変更しない。",
    "prior_evidence_sha256": prior["evidence_sha256"],
    "snapshot_audit_hash": digest(audit), "m3_checks": checks,
    "m3_complete": all(row["status"] == "passed" for row in checks),
}
keys = ("rights_eligible", "analysis_eligible", "representatives", "confirmed_subjects")
roles = {}
for domain in ("real_building", "real_terrain"):
    fields = ("subject_count", "effective_sample_size", "correction_rate", "no_information_rate",
              "attribute_unknown_rates", "condition4_role_gate", "flags")
    roles[domain] = {
        "old": {key: old["condition4"][domain][key] for key in fields},
        "new": {key: new["condition4"][domain][key] for key in fields},
    }
comparison = {
    "old_snapshot_id": old_snapshot["snapshot_id"], "new_snapshot_id": snapshot["snapshot_id"],
    "old_run_id": "d7297e42-3b35-49e2-a0f8-903809a9af59", "new_run_id": new["run_id"],
    "image_and_subject_counts": {
        "old": {key: old_snapshot["counts"][key] for key in keys},
        "new": {key: snapshot["counts"][key] for key in keys},
    },
    "roles": roles,
    "statistics": {
        "old": {key: old[key] for key in ("rows", "supported", "unsupported", "statuses")},
        "new": {key: new[key] for key in ("rows", "supported", "unsupported", "statuses")},
    },
    "condition4": {"old": old["condition4_passed"], "new": new["condition4_passed"]},
    "m3_checks": [{"condition": row["condition"], "status": row["status"]} for row in checks],
    "interpretation": new["interpretation"],
    "artifacts": {"root": str(root), "report_sha256": assessment["report_sha256"],
                  "registered_rows_hash": new["registered_result_hash"]},
}
for name, data in (("comparison.json", comparison), ("m3-assessment.json", assessment)):
    with (root / name).open("x", encoding="utf-8") as stream:
        stream.write(canonical(data) + "\n")
print(canonical(comparison))
