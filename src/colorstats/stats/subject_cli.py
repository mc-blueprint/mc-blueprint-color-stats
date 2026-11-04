"""保存済みメタデータの対象推定CLI。接続情報は表示しない。"""

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from time import monotonic

import yaml
from sqlalchemy import create_engine

from colorstats.schema.taxonomy import load_taxonomy
from colorstats.stats.subjects import execute
from colorstats.stats.wikidata import WikidataCatalog


def load_rules(path, taxonomy):
    rules = yaml.safe_load(path.read_text(encoding="utf-8"))
    scene = load_taxonomy(taxonomy)["scene"]
    if rules["taxonomy_version"] != scene["taxonomy_version"]:
        raise ValueError("taxonomy版が一致しません")
    keys = [(s["domain"], s["key"]) for s in rules["subjects"]]
    if len(keys) != len(set(keys)):
        raise ValueError("対象キーが重複しています")
    for attribute, values in rules["attributes"].items():
        if set(values) - set(scene["attributes"][attribute]):
            raise ValueError("taxonomyにない属性値です")
    for subject in rules["subjects"]:
        for attribute, value in subject.get("attributes", {}).items():
            if value not in scene["attributes"][attribute]:
                raise ValueError("taxonomyにない対象属性です")
    return rules


def main():
    parser = argparse.ArgumentParser(description="subjectと根拠付きシーン属性を推定する")
    parser.add_argument("--rules", type=Path, default=Path("configs/subject_rules.yaml"))
    parser.add_argument("--taxonomy", type=Path, default=Path("taxonomy"))
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--code-version", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reconsider-run", type=uuid.UUID, help="新規関連付けを再評価する成功run")
    parser.add_argument("--wikidata-cache", type=Path, help="自動対象キーの取得結果保存先")
    parser.add_argument("--source-policy", type=Path, default=Path("configs/source_policy.yaml"))
    parser.add_argument("--offline", action="store_true", help="保存取得結果だけで再実行する")
    args = parser.parse_args()
    if args.offline and args.wikidata_cache is None:
        parser.error("--offlineには--wikidata-cacheが必要です")
    started = monotonic()
    engine = None
    try:
        rules = load_rules(args.rules, args.taxonomy)
        catalog = None
        if args.wikidata_cache:
            policy = yaml.safe_load(args.source_policy.read_text(encoding="utf-8"))
            catalog = WikidataCatalog(
                policy["sources"]["wikimedia_commons"], args.wikidata_cache, offline=args.offline,
            )
        engine = create_engine(os.environ["DATABASE_URL"])
        result = execute(
            engine, rules, args.snapshot, code_version=args.code_version, dry_run=args.dry_run,
            reconsider_run=args.reconsider_run, wikidata=catalog,
        )
        print(json.dumps({
            k: v for k, v in result.items() if k not in ("assets", "wikidata", "subject_keys")
        } | {"seconds": round(monotonic() - started, 3)}, ensure_ascii=False))
    except Exception as error:
        print(f"対象推定に失敗しました: {type(error).__name__}", file=sys.stderr)
        return 1
    finally:
        if engine:
            engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
