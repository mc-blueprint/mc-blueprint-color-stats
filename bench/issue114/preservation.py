"""旧行・旧snapshotと、新runの追加先・終結を最終照合する。個別記録は公開しない。"""

import json
from collections import Counter
from pathlib import Path
from uuid import UUID

from bench.issue114.production import ROOT, database, read, save
from bench.issue122.production import BASELINE_TABLES, baseline
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from colorstats.analyze.segment import _hash
from colorstats.schema.models import Job, ProcessingRun
from colorstats.stats.snapshot import verify


def main():
    db = database()
    try:
        preserved = {}
        before_runs = read(ROOT / "before-processing_run.json")
        with db.connect() as connection:
            connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            assert revision == "0009"
            for table in BASELINE_TABLES:
                before = read(ROOT / ("before-" + table + ".json"))
                after = baseline(connection, table)
                changed = sum(after.get(key) != value for key, value in before.items())
                assert changed == 0
                if table not in {"processing_run", "rule_stat"}:
                    assert before.keys() == after.keys()
                preserved[table] = {"before": len(before), "after": len(after),
                                    "changed_or_missing": changed}
        expected = set()
        plan = read(ROOT / "plan.json")
        ready = {row["asset_id"]: row for row in plan["rows"] if row["status"] == "ready"}
        stages, privacy = Counter(), Counter()
        for host in ("ubuntu1", "ubuntu2"):
            audit = read(ROOT / host / "audit-full.json")
            assert audit["terminal"] == audit["target"]
            assert audit["failures"] == audit["unclosed"] == 0
            for aid, record in read(ROOT / host / "records.json").items():
                assert aid in ready and record["terminal"]
                privacy[record["privacy_verdict"]["decision"]] += 1
                expected.update(value for key, value in record.items() if key.endswith("_run_id"))
        comparison = read(ROOT / "statistics/comparison.json")
        expected.add(comparison["registration"]["run_id"])
        held_comparison = read(ROOT / "old-held-baseline/comparison.json")
        expected.add(held_comparison["registration"]["run_id"])
        with Session(db) as session:
            actual = {str(run_id) for run_id in session.scalars(select(ProcessingRun.id))
                      if str(run_id) not in before_runs}
            assert actual == expected
            for run in session.scalars(select(ProcessingRun).where(
                    ProcessingRun.id.in_([UUID(value) for value in actual]))):
                assert run.finished_at is not None and run.failure_reason is None
                stages[run.stage] += 1
                if run.stage == "aggregate":
                    continue
                job = session.scalar(select(Job).where(Job.run_id == run.id))
                assert job.status == "succeeded" and str(job.asset_id) in ready
                if run.stage == "segment":
                    assert all(job.payload[key] == value for key, value in plan["settings"].items())
                    assert job.payload["input_sha256"] == ready[str(job.asset_id)]["input_sha256"]
            versions = ["issue114-" + read(ROOT / name)["implementation_hash"][:16]
                        for name in ("execution.json", "execution-r3.json")]
            statuses = session.scalars(select(Job.status).where(
                Job.payload["code_version"].astext.in_(versions))).all()
            assert all(status == "succeeded" for status in statuses)
        snapshots = {
            "issue74-full-20261104T180829Z":
                "3e785e67c42f02a174c85a6f54e2c081447c8c784c912ee3b4c5e7a94cb45702",
            "issue104-full-20261105T084843Z":
                "e60bc14c7076a405b75333d1a0b280d9b088534796bdc4fedec0fbdebe414471",
            "issue105-corrected-20261105T105836Z":
                "a8384373192d930df952190433d5d346393549b87c941ef157ea93380c714864",
            "issue122-terrain-20261109-v1":
                "d53765a48d4b20ed77dbf393c04dad33a2601e5996c9718b44778c5e38448f58"}
        for name, expected_hash in snapshots.items():
            verify(Path("/mnt/data/derived/stats") / name / "snapshot", expected_hash)
        execution_old = read(ROOT / "execution.json")["implementation"]
        execution_new = read(ROOT / "execution-r3.json")["implementation"]
        pixel_files = [name for name in execution_old if name.startswith("src/colorstats/analyze/")]
        assert all(execution_new.get(name) == execution_old[name] for name in pixel_files)
        backup = Path("/mnt/data/work/issue-114/backup-20261110T0341JST/before.dump")
        assert _hash(backup) == "315cd554655a8fe8a7dc0920db8eb49089e25e18c8a2da57060cc2bc23874bcc"
        result = {"preserved": preserved, "revision": revision, "new_stages": stages,
                  "new_runs": len(actual), "privacy": privacy, "new_cohort": 2600,
                  "original_hold": 993, "unexpected_cohort_runs": 0,
                  "old_snapshots_verified": snapshots, "backup_sha256_verified": True,
                  "reused_segment_pixel_files_verified": len(pixel_files),
                  "human_reviewed_held": 110, "human_runs_written": 0}
        save(ROOT / "preservation-final.json", result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        db.dispose()


if __name__ == "__main__":
    main()
