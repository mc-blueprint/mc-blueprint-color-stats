"""#79と同じpeer認証による本番反映・読取り専用照合。接続情報は出力しない。"""

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from colorstats.schema.models import Asset, Subject
from colorstats.stats.subject_attributes import main


def audit(paths):
    dry, applied, replay = [json.loads(p.read_text(encoding="utf-8")) for p in paths[:3]]
    rows = [{r["subject_id"]: r for r in data["subjects"]} for data in (dry, applied, replay)]
    violations = Counter()
    for sid, row in rows[1].items():
        for other in (rows[0], rows[2]):
            violations["replay_difference"] += other[sid]["after"] != row["after"]
            violations["evidence_difference"] += other[sid]["evidence"] != row["evidence"]
        if row["evidence"] is None:
            violations["unsupported_value"] += any(row["after"].values())
        else:
            claims = row["evidence"]["claims"]
            country_ids = {
                c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
                for c in claims["P17"] if c.get("rank") != "deprecated"
            }
            region = row["attributes"]["region"]
            if region["state"] == "inferred":
                mapped = {applied["rules"]["countries"].get(q) for q in country_ids}
                violations["wrong_country_mapping"] += mapped != {region["value"]}
            era = row["attributes"]["era"]
            if era["state"] == "inferred":
                lo, hi = applied["rules"]["eras"][era["value"]]
                violations["wrong_era_mapping"] += not all(
                    lo <= a <= b <= hi for a, b in era["year_ranges"]
                )
        violations["overwritten_existing"] += sum(
            row["before"][key] is not None and row["before"][key] != row["after"][key]
            for key in ("region", "era")
        )
    engine = create_engine(URL.create("postgresql+psycopg", database="colorstats"))
    try:
        with Session(engine) as session, session.begin():
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            db = session.scalars(select(Subject).where(
                Subject.domain == "real_building",
                select(Asset.id).where(Asset.subject_id == Subject.id).exists(),
            )).all()
            confirmed_ids = {str(s.id) for s in db}
            violations["db_count_difference"] = abs(len(db) - len(rows[1]))
            violations["unconfirmed_in_result"] = len(rows[1].keys() - confirmed_ids)
            violations["db_value_difference"] = sum(
                rows[1][str(s.id)]["after"] != {"region": s.location, "era": s.era}
                for s in db
            )
            outside = session.scalars(select(Subject).where(
                Subject.domain == "real_building",
                ~select(Asset.id).where(Asset.subject_id == Subject.id).exists(),
            )).all()
            violations["unconfirmed_with_attributes"] = sum(
                s.location is not None or s.era is not None for s in outside
            )
    finally:
        engine.dispose()
    sample = {}
    for key in ("region", "era"):
        chosen = []
        groups = sorted({(r["attributes"][key]["reason"], r["after"][key] or "")
                         for r in applied["subjects"]})
        for reason, value in groups:
            chosen.extend([r for r in applied["subjects"]
                           if r["attributes"][key]["reason"] == reason
                           and (r["after"][key] or "") == value][:3])
        sample[key] = [{k: r[k] for k in ("subject_id", "name", "wikidata_ids", "evidence",
                                        "attributes")} for r in chosen]
    result = {
        "counts": applied["counts"], "reasons": applied["reasons"],
        "values": {key: dict(Counter(r["after"][key] for r in applied["subjects"]
                                     if r["after"][key] is not None)) for key in ("region", "era")},
        "run_id": applied["run_id"], "violations": dict(violations), "sample": sample,
        "confirmed_subjects": len(db), "unconfirmed_subjects": len(outside),
        "snapshots": [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                      for p in paths],
    }
    if len(paths) >= 5:
        cancelled, old = [json.loads(p.read_text(encoding="utf-8")) for p in paths[3:5]]
        original = {r["subject_id"]: r for r in old["subjects"]}
        violations["cancel_difference"] = sum(
            r["before"] != original[r["subject_id"]]["after"]
            or r["after"] != original[r["subject_id"]]["before"]
            for r in cancelled["subjects"]
        )
        result["cancellation"] = {
            "source_run": cancelled["cancel_run"], "run_id": cancelled["run_id"],
            "reverted": dict(Counter(key for _, key in cancelled["changes"])),
            "reverted_unconfirmed": dict(Counter(
                key for sid, key in cancelled["changes"] if sid not in confirmed_ids
            )),
        }
        result["violations"] = dict(violations)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(any(violations.values()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["run", "audit"])
    args, remaining = parser.parse_known_args()
    try:
        if args.mode == "audit":
            raise SystemExit(audit([Path(p) for p in remaining]))
        os.environ["DATABASE_URL"] = URL.create(
            "postgresql+psycopg", database="colorstats",
        ).render_as_string(hide_password=False)
        sys.argv = [sys.argv[0], *remaining]
        raise SystemExit(main())
    except Exception as error:
        print(f"本番検証に失敗しました: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
