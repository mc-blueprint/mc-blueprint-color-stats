"""固定snapshotのaggregate投入とDBなしのdry-run。"""

import argparse
import json
import os
import sys
from pathlib import Path
from time import monotonic

import yaml
from sqlalchemy import create_engine

from colorstats.collect.targets import load_targets
from colorstats.queue import Queue
from colorstats.schema.taxonomy import load_taxonomy
from colorstats.stats.aggregate import aggregate, config_hash
from colorstats.stats.snapshot import canonical, verify


def load_settings(config, targets, taxonomy):
    """既存の目標・taxonomy検証を再利用し、必要な契約だけ固定する。"""
    settings = yaml.safe_load(config.read_text(encoding="utf-8"))
    collection = load_targets(targets, taxonomy)
    documents = load_taxonomy(taxonomy)
    groups = documents["parts"]["groups"]
    parents = {label: group for group, labels in groups.items() for label in labels}
    order = [role for group, labels in groups.items() for role in (group, *labels)]
    order += ["tree", *documents["terrain"]["labels"]]
    if (not 0 < settings["mixed_min"] < settings["direct_min"]
            or settings["smoothing_strength"] <= 0):
        raise ValueError("支持閾値が不正です")
    return settings | {
        "taxonomy_version": collection["taxonomy_version"],
        "strata": [{k: s[k] for k in ("id", "attributes", "subjects")}
                   for s in collection["strata"]],
        "parents": parents, "role_order": order,
    }


def main():
    parser = argparse.ArgumentParser(description="固定snapshotの条件分布を検証・投入する")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--config", type=Path, default=Path("configs/stats.yaml"))
    parser.add_argument("--targets", type=Path, default=Path("configs/collection_targets.yaml"))
    parser.add_argument("--taxonomy", type=Path, default=Path("taxonomy"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    engine = None
    started = monotonic()
    try:
        settings = load_settings(args.config, args.targets, args.taxonomy)
        manifest = verify(args.snapshot, args.snapshot_id)
        if manifest["taxonomy_version"] != settings["taxonomy_version"]:
            raise ValueError("taxonomy版が一致しません")
        payload = {
            "snapshot": str(args.snapshot.resolve()), "snapshot_id": args.snapshot_id,
            "settings": settings, "output_path": str(args.output.resolve()),
        }
        if args.dry_run:
            data = aggregate(args.snapshot, args.snapshot_id, settings)
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(canonical(data) + "\n")
            result = {"rows": len(data["rows"]), "dry_run": True}
        else:
            engine = create_engine(os.environ["DATABASE_URL"])
            result = {"job_id": str(Queue(engine).enqueue(
                "aggregate", None, config_hash(payload), payload,
            )), "handler": "colorstats.stats.aggregate"}
        print(json.dumps(result | {"seconds": round(monotonic() - started, 3)}, ensure_ascii=False))
    except Exception as error:
        print(f"集計に失敗しました: {type(error).__name__}", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
