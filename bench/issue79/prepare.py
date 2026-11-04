"""抽出済みカテゴリとAPIキャッシュから、推定用カタログを保存する。"""

import argparse
import json
from pathlib import Path
from time import monotonic

import yaml

from colorstats.stats.subject_cli import load_rules
from colorstats.stats.subjects import digest
from colorstats.stats.wikidata import WikidataCatalog

parser = argparse.ArgumentParser()
parser.add_argument("input", type=Path)
parser.add_argument("cache", type=Path)
parser.add_argument("output", type=Path)
parser.add_argument("--offline", action="store_true")
args = parser.parse_args()
policy = yaml.safe_load(Path("configs/source_policy.yaml").read_text(encoding="utf-8"))
catalog = WikidataCatalog(policy["sources"]["wikimedia_commons"], args.cache, offline=args.offline)
started = monotonic()
rules = catalog.build(
    json.loads(args.input.read_text(encoding="utf-8"))["categories"],
    load_rules(Path("configs/subject_rules.yaml"), Path("taxonomy")),
)
with args.output.open("x", encoding="utf-8") as stream:
    json.dump(rules, stream, ensure_ascii=False, indent=2)
print(json.dumps({
    "seconds": round(monotonic() - started, 3), "config_hash": digest(rules),
    "targets": len(rules["subjects"]), "requests": len(catalog.requests),
    "automatic": sum(t["key"].startswith("wikidata:") for t in rules["subjects"]),
}, ensure_ascii=False))
