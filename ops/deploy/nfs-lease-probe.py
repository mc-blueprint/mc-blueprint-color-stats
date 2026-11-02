"""隔離DBで既定10分リースの継続・失効・旧所有権拒否を実測する。

DATABASE_URLは試験専用クラスタだけを指定する。本番では実行しない。
NFSのI/Oプロセスとは独立して動かし、親が更新できる場合と停止した場合を比較する。
"""

import json
import os
import time

from sqlalchemy import create_engine, select

from colorstats.queue import LeaseLost, Queue, RunInfo
from colorstats.schema.models import Base, Job


def event(name, **values):
    print(json.dumps({"event": name, "time": time.time(), **values}), flush=True)


def main():
    url = os.environ["DATABASE_URL"]
    if ":55442/" not in url:
        raise SystemExit("試験用ポート55442だけを指定してください")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    queue = Queue(engine)
    for stage in ("collect", "aggregate"):
        queue.enqueue(stage, None, stage, {})
    live = queue.claim(("collect",))
    expired = queue.claim(("aggregate",))
    event("claimed", lease_seconds=queue.lease.total_seconds())
    started = time.monotonic()
    for threshold in (200, 400, 610):
        while time.monotonic() - started < threshold:
            time.sleep(1)
        queue.renew(live)
        with engine.connect() as connection:
            rows = connection.execute(select(Job.stage, Job.status, Job.lease_until)).all()
        event("renew", elapsed=time.monotonic() - started,
              jobs=[list(map(str, row)) for row in rows])
    replacement = queue.claim(("aggregate",))
    assert replacement is not None and replacement.token != expired.token
    event("reclaimed", attempt=replacement.attempt)
    try:
        queue.complete(expired, RunInfo(code_version="issue42", taxonomy_version="0.1.0",
                                       node="ubuntu-2", license_class="open", parameters={}),
                       lambda session, run: None)
    except LeaseLost:
        event("stale_completion_rejected")
    else:
        raise AssertionError("失効試行を拒否しませんでした")
    assert queue.claim(("collect",)) is None
    event("renewed_claim_not_reclaimed")
    event("finished")


if __name__ == "__main__":
    main()
