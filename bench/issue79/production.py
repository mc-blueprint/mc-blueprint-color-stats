"""Issue #79の本番入力抽出と、スナップショットの独立照合。秘密情報は出力しない。"""

import argparse
import json
from collections import Counter
from pathlib import Path

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from colorstats.schema.models import Asset
from colorstats.stats.subject_cli import main

parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=["export", "run", "audit"])
parser.add_argument("path", type=Path)
parser.add_argument("--prior-snapshot", type=Path)
args, remaining = parser.parse_known_args()

if args.mode == "run":
    import os
    import sys

    os.environ["DATABASE_URL"] = URL.create(
        "postgresql+psycopg", database="colorstats",
    ).render_as_string(hide_password=False)
    sys.argv = [sys.argv[0], "--snapshot", str(args.path), *remaining]
    raise SystemExit(main())

if args.mode == "export":
    engine = create_engine(URL.create("postgresql+psycopg", database="colorstats"))
    with Session(engine) as session, session.begin():
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        assets = session.scalars(select(Asset)).all()
        categories = sorted({
            c["title"].removeprefix("Category:")
            for a in assets for c in (a.quality or {}).get("metadata", {}).get("categories", [])
        })
        result = {"asset_count": len(assets), "categories": categories}
    args.path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"asset_count": len(assets), "categories": len(categories)}))
    engine.dispose()
else:
    current = json.loads(args.path.read_text(encoding="utf-8"))
    baseline = json.loads(Path(remaining[0]).read_text(encoding="utf-8"))
    old = {r["asset_id"]: r for r in baseline["assets"]}
    changed = [
        r["asset_id"] for r in current["assets"]
        if old[r["asset_id"]]["subject_id"]
        and old[r["asset_id"]]["subject_id"] != r["subject_id"]
    ]
    new = [r for r in current["assets"] if r["subject_id"] and not old[r["asset_id"]]["subject_id"]]
    violations = Counter()
    for row in new:
        basis = row["candidates"].get(row["subject_id"], {})
        if any(reason in row["reasons"] for reason in (
            "multiple_targets", "sha_conflict", "location_conflict", "existing_conflict",
        )):
            violations["blocked_confirmed"] += 1
        if not basis.get("strong") and not basis.get("sha_support"):
            violations["unsupported"] += 1
    sha = {}
    for row in current["assets"]:
        if row["subject_id"]:
            sha.setdefault((row["domain"], row["sha256"]), set()).add(row["subject_id"])
    violations["sha_conflicts"] = sum(len(ids) > 1 for ids in sha.values())
    bindings = {item["subject_id"]: item for item in current["subject_keys"]}
    by_qid = {}
    for item in bindings.values():
        if item.get("wikidata_id"):
            by_qid.setdefault(item["wikidata_id"], set()).add(item["subject_id"])
    violations["duplicate_wikidata_subjects"] = sum(len(ids) > 1 for ids in by_qid.values())
    for row in new:
        qid = bindings.get(row["subject_id"], {}).get("wikidata_id")
        item = (current.get("wikidata") or {}).get("entities", {}).get(qid)
        if qid and item is None:
            violations["unqualified_wikidata"] += 1
        if item and item.get("candidate_only"):
            violations["coarse_new_confirmed"] += 1
    sample = [
        row for domain in ("real_building", "real_terrain")
        for row in list({
            r["subject_id"]: r for r in new if r["domain"] == domain
            and r["candidates"].get(r["subject_id"], {}).get("strong")
        }.values())[:6]
    ]
    result = {
        "counts": current["counts"], "confirmed_subjects": current["confirmed_subjects"],
        "origins": current["origins"],
        "subjects_by_origin": {
            domain: dict(Counter(
                "automatic" if bindings[sid]["key"].startswith("wikidata:") else "manual"
                for sid in {r["subject_id"] for r in current["assets"]
                            if r["domain"] == domain and r["subject_id"]}
            )) for domain in ("real_building", "real_terrain")
        },
        "preserved_changed": len(changed),
        "new_confirmed": len(new), "violations": dict(violations),
        "sample": [{
            "asset_id": r["asset_id"], "domain": r["domain"], "title": r["input"]["title"],
            "basis": r["candidates"].get(r["subject_id"]), "reasons": r["reasons"],
        } for r in sample],
    }
    if args.prior_snapshot:
        prior = json.loads(args.prior_snapshot.read_text(encoding="utf-8"))
        prior_rows = {row["asset_id"]: row for row in prior["assets"]}
        prior_keys = {b["subject_id"]: b["key"] for b in prior["subject_keys"]}
        revoked = [
            row for row in current["assets"]
            if prior_rows[row["asset_id"]]["subject_id"]
            and prior_rows[row["asset_id"]]["previous_subject_id"] is None
            and row["subject_id"] is None
        ]
        restored = [
            row for row in current["assets"]
            if row["previous_subject_id"] is None and row["subject_id"]
            and row["subject_id"] == prior_rows[row["asset_id"]]["subject_id"]
        ]
        result["revocations"] = {
            "count": len(revoked),
            "marked_in_this_execution": current["revoked_assignments"],
            "restored_from_intermediate_review": len(restored),
            "by_domain": dict(Counter(row["domain"] for row in revoked)),
            "by_key": dict(sorted(Counter(
                prior_keys[prior_rows[row["asset_id"]]["subject_id"]] for row in revoked
            ).items())),
            "by_reason": dict(Counter(reason for row in revoked for reason in row["reasons"])),
            "assets": [{
                "asset_id": row["asset_id"], "title": row["input"]["title"],
                "key": prior_keys[prior_rows[row["asset_id"]]["subject_id"]],
                "reasons": row["reasons"],
            } for row in revoked],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if changed or any(violations.values()):
        raise SystemExit(1)
