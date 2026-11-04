"""明示選択した解析runから固定スナップショットを作るCLI。"""

import argparse
import json
import os
import sys
from pathlib import Path
from time import monotonic

import yaml
from sqlalchemy import create_engine

from colorstats.stats.snapshot import execute


def load_quality(path):
    """固定した評価artifactを照合し、支持済み和集合のメンバーを設定へ取り込む。"""
    import hashlib

    quality = yaml.safe_load(path.read_text(encoding="utf-8"))
    root = path.resolve().parent.parent
    for key in ("plan", "decision", "mapping", "definition"):
        artifact = root / quality["evaluation"][key]
        actual = hashlib.sha256(artifact.read_text(encoding="utf-8").encode()).hexdigest()
        if actual != quality["evaluation"][key + "_sha256"]:
            raise ValueError("品質評価artifactのhashが一致しません")
    decision = json.loads((root / quality["evaluation"]["decision"]).read_text(encoding="utf-8"))
    quality["supported_by_domain"] = {
        domain: sorted(set(values["supported"]) & set(quality["quality"]["supported_labels"]))
        for domain, values in decision["domains"].items()
    }
    quality["group_members"] = {
        role: decision["group_support"][role]["members"]
        for role in quality["quality"]["supported_groups"]
        if decision["group_support"][role]["supported"]
    }
    return quality


def main():
    parser = argparse.ArgumentParser(description="D15適格な固定Parquetスナップショットを作る")
    parser.add_argument("--selection", type=Path, required=True,
                        help="assetと成功runの明示選択JSON")
    parser.add_argument("--quality", type=Path, default=Path("configs/segment_stats.yaml"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--code-version", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.dry_run and args.output is None:
        parser.error("--outputが必要です")
    engine = None
    started = monotonic()
    try:
        selection = json.loads(args.selection.read_text(encoding="utf-8"))
        quality = load_quality(args.quality)
        engine = create_engine(os.environ["DATABASE_URL"])
        result = execute(engine, selection, args.output, quality=quality,
                         code_version=args.code_version, dry_run=args.dry_run)
        print(json.dumps({
            "snapshot_id": result.get("snapshot_id"), "counts": result["counts"],
            "exclusions": result["exclusions"], "seconds": round(monotonic() - started, 3),
        }, ensure_ascii=False))
    except Exception as error:
        print(f"snapshot作成に失敗しました: {type(error).__name__}", file=sys.stderr)
        return 1
    finally:
        if engine:
            engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
