"""DBへ接続せず固定snapshotと集計JSONから偏りレポートを生成する。"""

import argparse
import json
import sys
from pathlib import Path

from colorstats.stats.aggregate_cli import load_settings
from colorstats.stats.report import markdown, report
from colorstats.stats.snapshot import canonical


def main():
    parser = argparse.ArgumentParser(description="固定snapshotの偏りとM3完成条件を報告")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument(
        "--statistics", type=Path, required=True, help="同じsnapshotのaggregate CLI出力JSON"
    )
    parser.add_argument("--config", type=Path, default=Path("configs/stats.yaml"))
    parser.add_argument("--targets", type=Path, default=Path("configs/collection_targets.yaml"))
    parser.add_argument("--taxonomy", type=Path, default=Path("taxonomy"))
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="未使用ディレクトリ（report.jsonとreport.mdを作成）",
    )
    args = parser.parse_args()
    try:
        settings = load_settings(args.config, args.targets, args.taxonomy)
        statistics = json.loads(args.statistics.read_text(encoding="utf-8"))
        data = report(args.snapshot, args.snapshot_id, statistics, settings)
        rendered = markdown(data)
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / "report.json").write_text(canonical(data) + "\n", encoding="utf-8")
        (args.output / "report.md").write_text(rendered, encoding="utf-8")
        print(canonical({"snapshot_id": data["snapshot_id"], "m3_complete": data["m3_complete"]}))
    except Exception as error:
        print(f"報告に失敗しました: {type(error).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
