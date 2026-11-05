"""100件比較の固定ID・通信枠・元画像不変・解析分母を照合する。"""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    rows = json.loads((args.root / "manifest.json").read_text())
    selection = json.loads((args.root / "selection.json").read_text())
    budget = json.loads((args.root / "budget.json").read_text())
    assert len(rows) == len({row["asset_id"] for row in rows}) == 100
    assert len({row["sha256"] for row in rows}) == 100
    assert [row["asset_id"] for row in rows] == [
        row["asset_id"] for row in selection["records"]
    ]
    assert Counter(row["domain"] for row in rows) == {"real_building": 50, "real_terrain": 50}
    assert budget["used"]["original"] == 0
    assert all(budget["used"][key] <= budget["limits"][key] for key in budget["used"])
    request_count = sum(
        event["value"] for row in rows
        for event in row.get("arms", {}).get("thumbnail-1.0", {}).get("events", [])
        if event["event"] == "request"
    )
    assert request_count == budget["used"]["thumbnail"]
    unchanged = 0
    for row in rows:
        arm = row["arms"]["original-1.0"]
        assert arm["acquisition"] == "existing_read_only" and arm["network_bytes"] == 0
        with Path(arm["path"]).open("rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == row["sha256"]
        unchanged += 1
        if row["status"] == "thumbnail_not_smaller":
            assert row["width"] <= 1280 and "thumbnail-1.0" not in row["arms"]
        if row["status"] == "acquired":
            assert "comparison" in row or "analysis_error" in row
        if "comparison" in row:
            assert row["comparison"]["truth_iou"] is None
    report = {
        "fixed_count": 100, "distinct_sha": 100, "originals_unchanged": unchanged,
        "budget": budget, "status": dict(Counter(row["status"] for row in rows)),
        "evaluated": sum("comparison" in row for row in rows),
        "analysis_failed": sum("analysis_error" in row for row in rows),
        "production_database": "接続なし。固定snapshotと原本の読取りだけ。",
    }
    with (args.root / "audit.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
