"""私有計画の件数と媒体到達性だけを表示する。個別情報は出力しない。"""

import argparse
import json
from collections import Counter
from pathlib import Path

from bench.issue114.production import ROOT, read

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--access", action="store_true")
    args = parser.parse_args()
    plan = read(ROOT / "plan.json")
    print(json.dumps({"counts": plan["counts"], "partitions": {
        host: len(read(ROOT / host / "inputs.json")) for host in ("ubuntu1", "ubuntu2")}}))
    if args.access:
        failures = Counter()
        for row in plan["rows"]:
            if row["status"] != "ready":
                continue
            try:
                with Path(row["input_path"]).open("rb") as stream:
                    stream.read(1)
            except OSError as error:
                failures[type(error).__name__] += 1
        print(json.dumps({"prep_access_failures": failures}))
