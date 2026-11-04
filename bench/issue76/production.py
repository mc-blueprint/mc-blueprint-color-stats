"""固定本番統計のREAD ONLY監査。秘密や接続URLを出力しない。"""

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from colorstats.schema.models import ProcessingRun, ProcessingRunInput, RuleStat
from colorstats.stats.snapshot import canonical, digest

RUN = UUID("d7297e42-3b35-49e2-a0f8-903809a9af59")
SNAPSHOT = "3e785e67c42f02a174c85a6f54e2c081447c8c784c912ee3b4c5e7a94cb45702"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--statistics", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    engine = None
    try:
        data = json.loads(args.statistics.read_text(encoding="utf-8"))
        if data["snapshot_id"] != SNAPSHOT:
            raise ValueError("指定snapshotと一致しません")
        engine = create_engine(URL.create("postgresql+psycopg", database="colorstats"),
                               connect_args={"options": "-c default_transaction_read_only=on "
                                             "-c lock_timeout=2000 -c statement_timeout=60000"})
        with Session(engine) as session, session.begin():
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            run = session.get(ProcessingRun, RUN)
            if run.finished_at is None or run.failure_reason or run.license_class != "open":
                raise ValueError("統計runが成功していません")
            rows = session.scalars(select(RuleStat).where(RuleStat.processing_run_id == RUN)).all()
            actual = [{key: getattr(row, key) for key in data["rows"][0]} for row in rows]
            if sorted(map(canonical, actual)) != sorted(map(canonical, data["rows"])):
                raise ValueError("本番rule_statとファイルが一致しません")
            inputs = sorted(str(rid) for rid in session.scalars(select(
                ProcessingRunInput.input_run_id,
            ).where(ProcessingRunInput.run_id == RUN)))
            if inputs != sorted(row["id"] for row in data["input_runs"]):
                raise ValueError("本番入力辺が一致しません")
            result = {
                "snapshot_id": SNAPSHOT, "run_id": str(RUN), "rows": len(rows),
                "statistics_hash": digest(data),
                "registered_result_hash": digest(sorted(data["rows"], key=canonical)),
                "input_run_count": len(inputs), "database_rows_equal": True,
                "read_only": session.scalar(text("SHOW transaction_read_only")),
                "isolation": session.scalar(text("SHOW transaction_isolation")),
            }
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(canonical(result) + "\n")
        print(canonical(result))
        return 0
    except Exception as error:
        print(f"本番読取り監査失敗: {type(error).__name__}", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
