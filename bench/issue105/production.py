"""#105の保存根拠による補完。DB例外や原metaを標準出力へ出さない。"""

import argparse
import hashlib
import json
import os
import pwd
import sys
import traceback
from collections import defaultdict
from pathlib import Path

import duckdb
import psycopg
import yaml
from sqlalchemy import create_engine, event, text

from colorstats.stats import snapshot as snapshot_module
from colorstats.stats import subject_attributes, supplement
from colorstats.stats.aggregate import _read as read_snapshot
from colorstats.stats.snapshot import canonical, digest, verify
from colorstats.stats.snapshot import execute as snapshot_execute
from colorstats.stats.snapshot_cli import load_quality

ROOT = Path("/mnt/data/work/issue-105")
CODE = Path(__file__).resolve().parents[2]
OLD = Path("/mnt/data/derived/stats/issue104-full-20261105T084843Z")
VERSION = "9c0011f+issue105-" + digest({
    str(p.relative_to(CODE)): hashlib.sha256(p.read_bytes()).hexdigest()
    for folder in ("src", "configs", "taxonomy") for p in sorted((CODE / folder).rglob("*"))
    if p.is_file() and "__pycache__" not in p.parts
})[:16]


def engine(readonly):
    def connect():
        previous = os.geteuid()
        os.seteuid(pwd.getpwnam("postgres").pw_uid)
        try:
            return psycopg.connect(dbname="colorstats", options=(
                "-c application_name=colorstats-issue105 -c lock_timeout=3000"
                + (" -c default_transaction_read_only=on" if readonly else "")))
        finally:
            os.seteuid(previous)
    result = create_engine("postgresql+psycopg://", creator=connect, hide_parameters=True)

    @event.listens_for(result, "connect")
    def priority(connection, record):
        os.setpriority(os.PRIO_PROCESS, connection.info.backend_pid, 19)

    return result


class SavedCatalog:
    client = type("Client", (), {"policy": {"user_agent": "offline-issue105"}})()

    def __init__(self):
        self.entities, self.requests = {}, {}
        for directory in ("cache", "review-evidence/cache"):
            for path in sorted((Path("/mnt/data/work/issue-79") / directory).glob("*.json")):
                data = json.loads(path.read_text())
                for qid, entity in data.get("entities", {}).items():
                    if "claims" in entity:
                        self.entities[qid] = entity
                self.requests[path.stem] = digest(data)

    def attribute_claims(self, ids):
        missing = set(ids) - self.entities.keys()
        if missing:
            raise FileNotFoundError(f"Wikidataキャッシュ不足: {len(missing)}")
        return {qid: {"revision": self.entities[qid].get("lastrevid"),
                      "claims": {p: self.entities[qid]["claims"].get(p, [])
                                 for p in ("P17", "P131", "P625", "P571")}}
                for qid in ids}


def preserved(db):
    with db.connect() as connection:
        values = {}
        for rid in ("d7297e42-3b35-49e2-a0f8-903809a9af59",
                    "3b46cfe4-9965-48d3-b041-b9b63bba75fc",
                    "928993fa-d498-4f68-85f4-35169d5d07c5"):
            values[rid] = digest(connection.execute(text(
                "select to_jsonb(r)::text from rule_stat r where processing_run_id=:rid order by id"
            ), {"rid": rid}).scalars().all())
        values["original_assets"] = digest([list(row) for row in connection.execute(text(
            "select (to_jsonb(a)-'quality'-'scene_attributes'-'subject_id')::text, "
            "(quality-'scene_inference'-'subject_inference')::text from asset a order by id"
        )).fetchall()])
        values["sources"] = digest(connection.execute(text(
            "select to_jsonb(s)::text from source s order by id")).scalars().all())
    for root in (Path("/mnt/data/derived/stats/issue74-full-20261104T180829Z"), OLD):
        manifest = json.loads((root / "snapshot/manifest.json").read_text())
        verify(root / "snapshot", manifest["snapshot_id"])
        values[root.name] = digest(manifest)
    return values


def saved_groups(quality):
    """#104と完全一致する解析入力・品質の和集合色だけを再利用する。"""
    manifest = json.loads((OLD / "snapshot/manifest.json").read_text())
    verify(OLD / "snapshot", manifest["snapshot_id"])
    assert quality == manifest["quality"]
    implementation = json.loads((OLD / "implementation.json").read_text())["files"]
    for name, expected in implementation.items():
        if name.startswith("src/colorstats/analyze/") or name == "src/colorstats/colors.py":
            assert hashlib.sha256((CODE / name).read_bytes()).hexdigest() == expected
    with duckdb.connect() as connection:
        for table in ("assets", "runs", "regions", "groups"):
            connection.read_parquet(str(OLD / "snapshot" / (table + ".parquet"))).create_view(table)
        assets = {r["id"]: r for r in read_snapshot(connection, "assets")}
        runs = {r["id"]: r["data"] for r in read_snapshot(connection, "runs")}
        regions = {r["id"]: r["data"] for r in read_snapshot(connection, "regions")}
        groups = defaultdict(list)
        for row in read_snapshot(connection, "groups"):
            groups[row["asset_id"]].append(row)

    def reuse(asset, chosen, current_regions, run, segment, settings):
        previous = assets[str(asset["id"])]
        assert previous["sha256"] == asset["sha256"]
        assert previous["domain"] == asset["domain"]
        assert settings == quality
        for stage in ("prep", "segment", "color"):
            assert previous["data"]["selection"][stage + "_run_id"] == str(chosen[stage])
        for current in (run, segment):
            assert canonical(current) == canonical(runs[str(current["id"])])
        for row in current_regions:
            assert canonical(snapshot_module._record(row, snapshot_module.REGION_COLUMNS)) == (
                canonical(regions[str(row["id"])]))
        for row in groups[str(asset["id"])]:
            assert row["run_id"] == str(chosen["color"])
            assert row["data"]["input_config_hash"] == run["config_hash"]
            assert row["quality_eligible"]
            yield dict(row, eligible=False, reasons=[])

    return reuse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["audit", "scene-dry", "scene-apply", "attrs-dry",
                                         "attrs-apply", "snapshot"])
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--plan", type=Path, default=ROOT / "results/scene-dry.json")
    parser.add_argument("--exif", type=Path)
    args = parser.parse_args()
    db = engine(not args.phase.endswith("apply"))
    try:
        if args.phase == "audit":
            result = preserved(db)
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(canonical(result) + "\n")
        elif args.phase.startswith("scene"):
            saved_rules = Path("/mnt/data/work/issue-79/review-evidence/rules.json")
            rules = json.loads(saved_rules.read_text())
            exif = json.loads(args.exif.read_text()) if args.exif else None
            expected = (json.loads(args.plan.read_text())["plan_hash"]
                        if args.phase.endswith("apply") else None)
            result = supplement.execute(
                db, rules, args.output, code_version=VERSION,
                dry_run=args.phase.endswith("dry"), expected_hash=expected, image_evidence=exif,
            ) if args.phase.endswith("apply") else supplement.execute(
                db, rules, args.output, code_version=VERSION, image_evidence=exif,
            )
            result = {k: v for k, v in result.items() if k not in {"assets", "subject_keys"}}
        elif args.phase.startswith("attrs"):
            rules = yaml.safe_load((CODE / "configs/subject_attributes.yaml").read_text())
            result = subject_attributes.execute(
                db, rules, SavedCatalog(), args.output, code_version=VERSION,
                dry_run=args.phase.endswith("dry"), domains=("real_building", "real_terrain"),
            )
            result = {k: result[k] for k in ("run_id", "changes", "counts", "reasons")}
        else:
            selection = json.loads((OLD / "selection.json").read_text())
            attributes = json.loads((ROOT / "results/attrs-apply.json").read_text())
            selection["subject_attribute_run_ids"] = [attributes["run_id"]]
            args.output.parent.mkdir(mode=0o700, exist_ok=False)
            (args.output.parent / "selection.json").write_text(canonical(selection) + "\n")
            settings = load_quality(CODE / "configs/segment_stats.yaml")
            snapshot_module._groups = saved_groups(settings)
            result = snapshot_execute(db, selection, args.output, quality=settings,
                                      code_version=VERSION)
            result = {k: result[k] for k in ("snapshot_id", "counts")}
        print(canonical(result))
    finally:
        db.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(canonical({"error": type(error).__name__, "frames": [
            [Path(f.filename).name, f.lineno] for f in traceback.extract_tb(error.__traceback__)
        ]}), file=sys.stderr)
        raise SystemExit(1) from None
