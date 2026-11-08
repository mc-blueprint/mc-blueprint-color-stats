"""既知標本の対応・所見と実装を予測前に固定する。出力はprivateへ置く。"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def freeze(source, output, *, aerial, unknown, low_saturation):
    """canonicalは改変せず、上空/低彩度の追加視覚確認と分離する。"""
    source, output = Path(source), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    records = json.loads((source / "human-evaluation-private.json").read_text(
        encoding="utf-8"))["records"]
    assert len(records) == 110
    for row in records:
        number = row["number"]
        row["aerial_truth"] = None if number in unknown else number in aerial
        row["low_saturation_color"] = number in low_saturation
        row["split"] = "adjustment" if number % 2 else "confirmation"
    manifest = {
        "version": "issue129-regression-v1", "seed": 129,
        "independent_evaluation": False,
        "additional_visual_review": "既存提示画像を予測前に担当が確認。canonicalとは別の補助正解",
        "split_rule": "既知標本の番号奇数を調整、偶数を確認。独立盲検とは呼ばない",
        "sources": {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                    for name in ("human-evaluation-private.json", "number-map.json",
                                 "user-reply-canonical.txt", "review.html")},
        "records": records,
    }
    target = output / "review-freeze.json"
    if target.exists():
        assert json.loads(target.read_text(encoding="utf-8")) == manifest
    else:
        with target.open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
    print("review_freeze_sha256=" + hashlib.sha256(target.read_bytes()).hexdigest())


def dependency(commit, output):
    files = {name: subprocess.check_output([
        "git", "show", f"{commit}:bench/issue121/{name}.json",
    ]).replace(b"\r\n", b"\n") for name in ("decision", "handoff")}
    decision_sha = hashlib.sha256(files["decision"]).hexdigest()
    assert json.loads(files["handoff"])["decision_sha256"] == decision_sha
    value = {"commit": commit, "decision_sha256": decision_sha,
             "handoff_sha256": hashlib.sha256(files["handoff"]).hexdigest(),
             "published_pr": 131}
    target = Path(output) / "dependency.json"
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("output")
    parser.add_argument("--aerial", type=int, nargs="+", required=True)
    parser.add_argument("--unknown", type=int, nargs="+", required=True)
    parser.add_argument("--low-saturation", type=int, nargs="+", required=True)
    parser.add_argument("--dependency-commit", required=True)
    args = parser.parse_args()
    freeze(args.source, args.output, aerial=args.aerial, unknown=args.unknown,
           low_saturation=args.low_saturation)
    dependency(args.dependency_commit, args.output)
