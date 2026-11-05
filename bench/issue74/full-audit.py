"""固定snapshotだけで全量の権利・由来・失敗非算入を再照合する。"""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import duckdb

from colorstats.stats.licenses import exclusion_reasons
from colorstats.stats.snapshot import TABLES, digest, verify


def audit(root, expected):
    """DB・画像に接続せず照合し、不一致はAssertionErrorで停止する。"""
    manifest = verify(root / "snapshot", expected)
    selection = json.loads((root / "selection.json").read_text(encoding="utf-8"))
    inputs = json.loads((root / "input-audit.json").read_text(encoding="utf-8"))
    assert digest(selection) == manifest["selection_hash"]
    reports = []
    for index, record in enumerate(selection["analysis_reports"]):
        path = root / "input-evidence" / f"report-{index}.json"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
        reports.append(json.loads(path.read_text(encoding="utf-8")))
    cohort = selection["cohort_manifest"]
    assert hashlib.sha256(
        (root / "input-evidence/cohort.json").read_bytes(),
    ).hexdigest() == cohort["sha256"]
    expected_rows = {
        "regions": sum(r["stages"]["segment"]["regions"] for r in reports),
        "part_observations": sum(r["stages"]["color"]["part_observations"] for r in reports),
        "relations": sum(r["stages"]["color"]["relations"] for r in reports),
    }
    with duckdb.connect(config={"threads": 1}) as db:
        for name in TABLES:
            db.read_parquet(str(root / "snapshot" / (name + ".parquet"))).create_view(name)
        assets = db.execute(
            "SELECT id, rights_eligible, eligible, reasons, data FROM assets ORDER BY id",
        ).fetchall()
        sources = {aid: json.loads(data) for aid, data in db.execute(
            "SELECT asset_id, data FROM provenance",
        ).fetchall()}
        runs = {rid: json.loads(data) for rid, data in db.execute(
            "SELECT id, data FROM runs",
        ).fetchall()}
        assert set(runs) == set(manifest["input_run_ids"])
        assert len(assets) == len(selection["assets"]) == inputs["assets"] == 7607
        actual_rows = {
            "regions": db.execute("SELECT count(*) FROM regions").fetchone()[0],
            "part_observations": db.execute(
                "SELECT count(*) FROM observations WHERE region_id IS NOT NULL",
            ).fetchone()[0],
            "relations": db.execute("SELECT count(*) FROM relations").fetchone()[0],
        }
        assert actual_rows == expected_rows, (actual_rows, expected_rows)
        violations = Counter()
        attribute_assets, attribute_subjects, states = 0, set(), Counter()
        attribute_rights = 0
        subject_states, subject_values, evidence_hashes = Counter(), Counter(), {}
        attribution = Counter()
        for aid, rights, eligible, reasons, raw in assets:
            data = json.loads(raw)
            source = sources[aid]
            chosen = data["selection"]
            todo = [chosen[k] for k in ("prep_run_id", "segment_run_id", "color_run_id")
                    if chosen.get(k)]
            todo += [data["quality"][k]["run_id"]
                     for k in ("subject_inference", "scene_inference")
                     if data["quality"].get(k, {}).get("run_id")]
            adopted = {}
            while todo:
                rid = todo.pop()
                if rid not in adopted:
                    run = runs[rid]
                    assert run["finished_at"] and run["failure_reason"] is None
                    adopted[rid] = run
                    todo.extend(run["input_run_ids"])
            gate_data = dict(data) | {
                "quality": dict(data["quality"]) | {"license": data["d15_license"]["asset"]},
            }
            gate_source = dict(source) | {"license": data["d15_license"]["source"]}
            excluded = exclusion_reasons(gate_data, gate_source, adopted.values())
            violations["rights"] += rights != (not excluded)
            violations["rights_reasons"] += bool(set(excluded) - set(json.loads(reasons)))
            if eligible:
                attribution["missing_url"] += not bool(source["url"])
                if (source["license_class"] != "analysis_only"
                        or source["policy"].get("attribution_required")):
                    attribution["missing_attribution"] += not bool(source["attribution"])
                attribution["restricted_source"] += source["license_class"] not in {
                    "open", "analysis_only",
                }
            subject = data["subject"]
            if subject and (evidence := subject.get("attribute_evidence")):
                attribute_assets += 1
                attribute_rights += int(rights)
                sid = subject["id"]
                evidence_hash = digest(evidence)
                assert evidence_hashes.get(sid, evidence_hash) == evidence_hash
                if sid not in attribute_subjects:
                    for key, column in (("region", "location"), ("era", "era")):
                        subject_states[key + ":" + evidence["attributes"][key]["state"]] += 1
                        subject_values[key] += subject[column] is not None
                attribute_subjects.add(sid)
                evidence_hashes[sid] = evidence_hash
                assert evidence["run_id"] in selection["subject_attribute_run_ids"]
                assert evidence["run_id"] in runs
                assert evidence["snapshot_sha256"]
                for key, column in (("region", "location"), ("era", "era")):
                    attribute = evidence["attributes"][key]
                    assert subject[column] == attribute["value"] == evidence["after"][key]
                    states[key + ":" + attribute["state"]] += 1
        violations.update(attribution)
        violations["sha_representative"] = db.execute("""
            WITH expected AS (
                SELECT sha256, min(id) AS id FROM assets
                WHERE rights_eligible AND analysis_available GROUP BY sha256
            )
            SELECT count(*) FROM assets a LEFT JOIN expected e USING (sha256)
            WHERE a.representative_id IS DISTINCT FROM e.id
               OR a.eligible <> (a.id IS NOT DISTINCT FROM e.id)
        """).fetchone()[0]
        failed = {r["asset_id"] for r in inputs["prep_failed"] + inputs["analysis_failed"]}
        assert len(inputs["prep_failed"]) == 4 and len(inputs["analysis_failed"]) == 2
        assert len(failed) == 6
        failures = []
        for aid, _rights, eligible, reasons, _raw in assets:
            if aid in failed:
                assert not eligible and "missing_analysis" in json.loads(reasons)
                failures.append(aid)
        assert set(failures) == failed
        for table in ("observations", "relations", "groups"):
            violations[table + "_eligibility"] = db.execute(f"""
                SELECT count(*) FROM {table} o JOIN assets a ON a.id = o.asset_id
                WHERE o.eligible <> (a.eligible AND o.quality_eligible)
            """).fetchone()[0]
            for aid in failed:
                assert db.execute(
                    f"SELECT count(*) FROM {table} WHERE asset_id = ? AND eligible", [aid],
                ).fetchone()[0] == 0
        roles = db.execute("""
            SELECT g.role, count(*), count(*) FILTER (WHERE a.rights_eligible),
                   count(*) FILTER (WHERE g.eligible),
                   count(DISTINCT a.subject_id) FILTER (WHERE g.eligible)
            FROM groups g JOIN assets a ON a.id = g.asset_id GROUP BY g.role ORDER BY g.role
        """).fetchall()
        reasons = db.execute("""
            SELECT reason, count(*) FROM assets, unnest(reasons::VARCHAR[]) t(reason)
            GROUP BY reason ORDER BY reason
        """).fetchall()
        assert all(value == 0 for value in violations.values()), dict(violations)
        assert attribute_subjects and set(selection["subject_attribute_run_ids"]) <= set(runs)
        return {
            "snapshot_id": expected, "verified_files": len(manifest["files"]),
            "counts": manifest["counts"], "exclusions": dict(reasons),
            "successful_stages": inputs["successful_stages"],
            "failed_assets": len(failed), "failed_contributions": 0,
            "attribute_assets": attribute_assets, "attribute_subjects": len(attribute_subjects),
            "attribute_rights_eligible": attribute_rights,
            "report_row_counts": actual_rows,
            "attribute_states_by_asset": dict(states),
            "attribute_states_by_subject": dict(subject_states),
            "attribute_known_subjects": dict(subject_values),
            "run_stages": dict(Counter(r["stage"] for r in runs.values())),
            "roles": [{"role": r[0], "before_d15": r[1], "after_d15": r[2],
                       "after_sha": r[3], "subjects": r[4]} for r in roles],
            "violations": dict(violations),
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--hash", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.root, args.hash)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))
