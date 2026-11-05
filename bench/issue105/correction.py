"""#105が所有する推定値だけを訂正し、旧版を保持して新snapshotを作成する。"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml
from sqlalchemy import text

from colorstats.stats import snapshot as snapshot_module
from colorstats.stats import supplement
from colorstats.stats.snapshot import canonical, digest, execute, verify
from colorstats.stats.snapshot_cli import load_quality
from colorstats.stats.subject_attributes import derive

sys.path.insert(0, str(Path(__file__).resolve().parent))
from production import CODE, ROOT, engine, preserved, saved_groups  # noqa: E402

REVISION = ROOT / "correction-v2"
PREVIOUS = Path("/mnt/data/derived/stats/issue105-full-20261105T101712Z")
REFERENCES = ["a1b2b69c-b063-4083-884c-92d41fee8e52", "4fba8d08-18da-40eb-825c-14ebdb90f8ce"]
VERSION = "4d9dcdb+i105-correction-v2-" + digest({
    str(p.relative_to(CODE)): hashlib.sha256(p.read_bytes()).hexdigest()
    for folder in ("src", "configs", "taxonomy") for p in sorted((CODE / folder).rglob("*"))
    if p.is_file() and "__pycache__" not in p.parts
})[:16]


def audit(db):
    result = preserved(db)
    manifest = json.loads((PREVIOUS / "snapshot/manifest.json").read_text())
    verify(PREVIOUS / "snapshot", manifest["snapshot_id"])
    result["previous_issue105_snapshot"] = digest(manifest)
    with db.connect() as connection:
        result["previous_issue105_statistics"] = digest(connection.execute(text(
            "select to_jsonb(r)::text from rule_stat r where processing_run_id="
            "'7c261582-b654-47af-bbb1-bcb08ecb4e1a' order by id")).scalars().all())
        result["subjects"] = digest(connection.execute(text(
            "select to_jsonb(s)::text from subject s order by id")).scalars().all())
        result["asset_identity"] = digest([list(r) for r in connection.execute(text(
            "select id::text,subject_id::text from asset order by id"))])
        attributes = json.loads((ROOT / "results/attrs-apply.json").read_text())
        rules = yaml.safe_load((CODE / "configs/subject_attributes.yaml").read_text())
        checked = 0
        for row in attributes["subjects"]:
            if not any(sid == row["subject_id"] for sid, _ in attributes["changes"]):
                continue
            derived = derive(row["evidence"], rules)
            actual = connection.execute(text(
                "select location,era from subject where id=:id"),
                {"id": row["subject_id"]}).one()
            assert actual.location == row["after"]["region"] == derived["region"]["value"]
            assert actual.era == row["after"]["era"]
            checked += 1
        result["region_values_rechecked"] = checked
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["audit", "dry", "apply", "snapshot"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    db = engine(args.mode != "apply")
    try:
        if args.mode == "audit":
            result = audit(db)
            with args.output.open("x") as stream:
                stream.write(canonical(result) + "\n")
        elif args.mode in ("dry", "apply"):
            expected = None
            if args.mode == "apply":
                if args.plan is None or args.backup is None:
                    raise ValueError("保存済みdry-runとbackup記録が必要です")
                expected = json.loads(args.plan.read_text())["plan_hash"]
                backup = json.loads(args.backup.read_text())
                with Path(backup["path"]).open("rb") as stream:
                    assert hashlib.file_digest(stream, "sha256").hexdigest() == backup["sha256"]
            rule_path = Path("/mnt/data/work/issue-79/review-evidence/rules.json")
            rules = json.loads(rule_path.read_text())
            evidence = json.loads((ROOT / "results/exif.json").read_text())
            result = supplement.execute(db, rules, args.output, code_version=VERSION,
                                        correction_runs=REFERENCES, image_evidence=evidence,
                                        dry_run=args.mode == "dry", expected_hash=expected)
            result = {k: v for k, v in result.items() if k not in {"assets", "subject_keys"}}
        else:
            selection = json.loads((PREVIOUS / "selection.json").read_text())
            args.output.parent.mkdir(mode=0o700, exist_ok=False)
            (args.output.parent / "selection.json").write_text(canonical(selection) + "\n")
            quality = load_quality(CODE / "configs/segment_stats.yaml")
            snapshot_module._groups = saved_groups(quality)
            result = execute(db, selection, args.output, quality=quality, code_version=VERSION)
            previous = json.loads((PREVIOUS / "snapshot/manifest.json").read_text())
            unchanged = {name: result["files"][name] == previous["files"][name]
                         for name in previous["files"] if name not in
                         ("assets.parquet", "runs.parquet")}
            assert all(unchanged.values())
            result = {k: result[k] for k in ("snapshot_id", "counts")} | {"unchanged": unchanged}
        print(canonical(result))
    finally:
        db.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        import traceback

        print(canonical({"error": type(error).__name__, "frames": [
            [Path(f.filename).name, f.lineno] for f in traceback.extract_tb(error.__traceback__)
        ]}), file=sys.stderr)
        raise SystemExit(1) from None
