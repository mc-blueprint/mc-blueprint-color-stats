"""隔離DBと新規保存先だけでCommonsの既定取得・原本再判定を確認する。"""

import hashlib
import json
import os
import sys
from collections import Counter
from functools import partial
from pathlib import Path

import yaml
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from colorstats.collect import SearchRequest, quality, stage
from colorstats.collect.commons import CommonsAdapter
from colorstats.collect.http import MeasurementLimit
from colorstats.queue import Queue
from colorstats.schema.models import Asset, Job, ProcessingRun

root = Path(sys.argv[1])
budget = {"limits": {"api": 10, "images": 20}, "used": {"api": 0, "images": 0}}
events = []


class BudgetAdapter(CommonsAdapter):
    def observe(self, event, value=1):
        if event in ("api_request", "request"):
            key = "api" if event == "api_request" else "images"
            if budget["used"][key] >= budget["limits"][key]:
                raise MeasurementLimit(key)
            budget["used"][key] += 1
            (root / "budget.json").write_text(json.dumps(budget, indent=2))
        events.append({"event": event, "value": value})
        super().observe(event, value)


stage.CommonsAdapter = BudgetAdapter
storage = root / "storage.yaml"
storage.write_text(yaml.safe_dump({"storage": {"raw": [
    {"host": "ubuntu-1", "path": str(root / "raw")},
]}}))
(root / "budget.json").write_text(json.dumps(budget, indent=2))
command.upgrade(Config("alembic.ini"), "head")
engine = create_engine(os.environ["DATABASE_URL"])
queue = Queue(engine)
runs = []
for query, mode in [("Himeji Castle", None), ("Mont Saint Michel", "original")]:
    request = SearchRequest("wikimedia_commons", query, limit=1, download_mode=mode)
    job = stage.enqueue_collect(
        queue, request, policy_path=Path("configs/source_policy.yaml"), storage_config=storage,
        host="ubuntu-1", domain="real_building", code_version="issue-109",
        taxonomy_version="0.1.0",
    )
    claim = queue.claim(["collect"], job_ids=[job])
    prepared = stage.prepare(claim)
    run_id = queue.complete(claim, prepared.info, partial(stage.register, data=prepared.data),
                            prepared.files)
    runs.append(str(run_id))
with Session(engine) as session:
    before = {str(asset.id): (asset.sha256, asset.storage_path, asset.quality)
              for asset in session.scalars(select(Asset))}
    collect_parameters = {identifier: session.get(ProcessingRun, identifier).parameters
                          for identifier in runs}
review_count = 0
while claim := queue.claim(["review"]):
    prepared = quality.prepare(claim)
    queue.complete(claim, prepared.info, partial(quality.register, data=prepared.data),
                   prepared.files)
    review_count += 1
with Session(engine) as session:
    after = {str(asset.id): (asset.sha256, asset.storage_path, asset.quality)
             for asset in session.scalars(select(Asset))}
    assert before == after
    assert all(session.get(ProcessingRun, identifier).parameters == parameters
               for identifier, parameters in collect_parameters.items())
    report = {
        "budget": budget, "assets": len(after), "review_jobs": review_count,
        "collect_runs": collect_parameters,
        "variants": dict(Counter(asset.quality["rendition"]["variant"]
                                  for asset in session.scalars(select(Asset)))),
        "jobs": session.scalar(select(func.count()).select_from(Job)),
        "existing_assets_and_runs_unchanged": True,
        "reviews": [run.parameters for run in session.scalars(select(ProcessingRun).where(
            ProcessingRun.stage == "review",
        ))],
        "received_bytes": sum(Path(path).stat().st_size for _, path, _ in after.values()),
        "raw_sha256": {identifier: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                       for identifier, (_, path, _) in after.items()},
    }
(root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
(root / "events.json").write_text(json.dumps(events, ensure_ascii=False, indent=2))
print(json.dumps({key: report[key] for key in (
    "budget", "assets", "review_jobs", "variants", "received_bytes",
    "existing_assets_and_runs_unchanged",
)}, ensure_ascii=False))
engine.dispose()
