"""#104の固定コホート再評価。秘密・画像・原metaを出力しない。"""

import argparse
import json
from pathlib import Path
from uuid import UUID

import yaml
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from colorstats.stats.reassess import execute
from colorstats.stats.snapshot import canonical


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["dry", "apply"])
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=Path("configs/source_policy.yaml"))
    parser.add_argument("--dry-result", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    selection = json.loads(args.selection.read_text(encoding="utf-8"))
    policies = yaml.safe_load(args.policy.read_text(encoding="utf-8"))["sources"]
    expected = None
    if args.mode == "apply":
        if args.dry_result is None:
            parser.error("保存済み--dry-resultが必要です")
        expected = json.loads(args.dry_result.read_text(encoding="utf-8"))["plan_hash"]
    engine = create_engine(URL.create("postgresql+psycopg", database="colorstats"),
                           hide_parameters=True, connect_args={"options": (
                               "-c lock_timeout=2000 -c statement_timeout=60000 "
                               "-c application_name=colorstats-issue104"
                               + (" -c default_transaction_read_only=on"
                                  if args.mode == "dry" else "")
                           )})
    # 出力先の衝突は本番取引より前に拒否する。
    with args.output.open("x", encoding="utf-8") as stream:
        try:
            result = execute(engine, [UUID(row["asset_id"]) for row in selection["assets"]],
                             policies, apply=args.mode == "apply", expected_hash=expected)
            stream.write(canonical(result) + "\n")
            stream.flush()
            print(canonical(result))
        finally:
            engine.dispose()


if __name__ == "__main__":
    main()
