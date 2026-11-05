"""確認根拠の訂正計画と実行。区分・元情報は訂正対象に含めない。"""

import argparse
import json
from pathlib import Path
from uuid import UUID

import yaml
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from colorstats.stats.reassess import correct_review
from colorstats.stats.snapshot import canonical

parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=("dry", "apply"))
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--plan", type=Path)
args = parser.parse_args()
previous = json.loads(Path("bench/issue104/rights-review-v1.json").read_text(encoding="utf-8"))
corrected = yaml.safe_load(Path("configs/source_policy.yaml").read_text(encoding="utf-8"))[
    "sources"
]["wikimedia_commons"]["rights_review"]
selection = json.loads(Path(
    "/mnt/data/derived/stats/issue74-full-20261104T180829Z/selection.json",
).read_text())
expected = json.loads(args.plan.read_text())["preserved_hash"] if args.plan else None
engine = create_engine(URL.create("postgresql+psycopg", database="colorstats"),
                       hide_parameters=True, connect_args={"options": (
                           "-c lock_timeout=2000 -c application_name=colorstats-issue104-rights-v2"
                           + (" -c default_transaction_read_only=on" if args.mode == "dry" else "")
                       )})
try:
    with args.output.open("x", encoding="utf-8") as stream:
        result = correct_review(
            engine, [UUID(row["asset_id"]) for row in selection["assets"]],
            previous, corrected, apply=args.mode == "apply", expected_hash=expected,
        )
        assert result["assets"] == 4531
        stream.write(canonical(result) + "\n")
        print(canonical(result))
finally:
    engine.dispose()
