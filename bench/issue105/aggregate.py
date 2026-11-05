"""固定snapshotを既存Queue・集計handlerへ登録し、全行・入力辺を照合する。"""

import json
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from colorstats.queue import Queue
from colorstats.schema.models import Job, ProcessingRun, ProcessingRunInput, RuleStat
from colorstats.stats import aggregate as handler
from colorstats.stats.aggregate_cli import load_settings
from colorstats.stats.snapshot import canonical, digest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from production import engine  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bench.issue75.production import summarize  # noqa: E402


def main():
    root = Path(sys.argv[1])
    manifest = json.loads((root / "snapshot/manifest.json").read_text())
    settings = load_settings(Path("configs/stats.yaml"), Path("configs/collection_targets.yaml"),
                             Path("taxonomy"))
    db = engine(False)
    try:
        payload = {"snapshot": str(root / "snapshot"), "snapshot_id": manifest["snapshot_id"],
                   "settings": settings, "output_path": str(root / "aggregate/statistics.json")}
        data = handler.aggregate(root / "snapshot", manifest["snapshot_id"], settings)
        with (root / "aggregate/dry.json").open("x") as stream:
            stream.write(canonical(data) + "\n")
        queue = Queue(db, lease=timedelta(minutes=30), timeout=30)
        with Session(db) as session:
            active = session.scalar(select(func.count()).select_from(Job).where(
                Job.stage == "aggregate", Job.status.in_(["pending", "running"])))
            if active:
                raise ValueError("他のaggregateが稼働中です")
        job_id = queue.enqueue("aggregate", None, handler.config_hash(payload), payload)
        claim = queue.claim(["aggregate"])
        if claim is None or claim.id != job_id:
            raise ValueError("指定jobを取得できません")
        try:
            prepared = handler.prepare(claim)
            if prepared.data != data:
                raise ValueError("事前計算と登録前の計算が一致しません")
            queue.renew(claim)
            rid = queue.complete(claim, prepared.info,
                                 lambda session, run: handler.register(session, run, data),
                                 prepared.files)
        except Exception as error:
            queue.fail(claim, type(error).__name__)
            raise
        with Session(db) as session:
            run = session.get(ProcessingRun, rid)
            rows = session.scalars(select(RuleStat).where(RuleStat.processing_run_id == rid)).all()
            actual = [{key: getattr(row, key) for key in data["rows"][0]} for row in rows]
            assert sorted(map(canonical, actual)) == sorted(map(canonical, data["rows"]))
            links = sorted(str(r) for r in session.scalars(select(ProcessingRunInput.input_run_id)
                                                         .where(ProcessingRunInput.run_id == rid)))
            assert links == sorted(row["id"] for row in data["input_runs"])
            result = summarize(data) | {
                "run_id": str(rid), "job_id": str(job_id), "license_class": run.license_class,
                "database_rows_equal": True, "input_edges_equal": True,
                "output_paths": run.output_paths,
                "registered_rows_hash": digest(sorted(data["rows"], key=canonical)),
            }
        with (root / "aggregate/registration.json").open("x") as stream:
            stream.write(canonical(result) + "\n")
        print(canonical({k: v for k, v in result.items() if k != "support"}))
    finally:
        db.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(type(error).__name__, file=sys.stderr)
        raise SystemExit(1) from None
