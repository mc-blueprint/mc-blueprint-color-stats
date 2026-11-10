"""#121の私有返信を照合し、当時の提示参照がない場合は取込せず保留する。"""

import argparse
import hashlib
import json
from pathlib import Path

from bench.issue114.mobile import apply_privacy_reply, parse_chat_reply


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(source, output):
    evaluation = json.loads((source / "human-evaluation-private.json").read_text(encoding="utf-8"))
    summary = evaluation["summary"]
    names = {"original_reply_sha256": "user-reply-original.md",
             "human_reply_sha256": "user-reply-canonical.txt",
             "number_map_sha256": "number-map.json", "presentation_sha256": "review.html"}
    raw = {key: (source / name).read_bytes() for key, name in names.items()}
    hashes = {key: hashlib.sha256(value).hexdigest() for key, value in raw.items()}
    assert all(summary[key] == value for key, value in hashes.items())
    mapping = json.loads(raw["number_map_sha256"])
    rows = mapping["rows"]
    assert [row["number"] for row in rows] == list(range(1, len(rows) + 1))
    assert {row["asset_id"] for row in rows} == {
        row["asset_id"] for row in evaluation["records"]}
    parsed = parse_chat_reply(raw["human_reply_sha256"].decode("utf-8"), len(rows))
    assert len(parsed["problems"]) == summary["problem_count"]
    missing = sum(not row.get("privacy_review_run_id") or
                  not row.get("region_policy_run_id") or
                  not row.get("presented_source_sha256") for row in rows)
    # 未提示の本番runを番号表へ後付けしない。
    if missing != len(rows):
        raise ValueError("提示参照のある返信は本番runとの追加照合が必要です")
    try:
        apply_privacy_reply(None, {"rows": rows})
    except ValueError as error:
        rejected = str(error)
    else:
        raise AssertionError("#120が必須参照のない返信を拒否しませんでした")
    result = {"status": "held_missing_presented_references", "reviewed": len(rows),
              "reported_problems": len(parsed["problems"]), "missing_references": missing,
              "human_runs_written": 0, "database_connected": False,
              "canonical_completion_assumed": not summary["completion_explicit_in_original"],
              "original_reply_reused_for_v2": False, "guard_error": rejected,
              "hashes": hashes, "requires_new_presentation": True}
    output.mkdir(parents=True, exist_ok=True)
    with (output / "preflight.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    with (output / "holds-private.json").open("x", encoding="utf-8") as stream:
        json.dump({"asset_ids": [row["asset_id"] for row in rows], "proof": result}, stream,
                  ensure_ascii=False, indent=2)
    assert all(sha256(source / name) == value for name, value in (
        ("user-reply-original.md", hashes["original_reply_sha256"]),
        ("user-reply-canonical.txt", hashes["human_reply_sha256"]),
        ("number-map.json", hashes["number_map_sha256"]),
        ("review.html", hashes["presentation_sha256"])))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit(args.source, args.output)
