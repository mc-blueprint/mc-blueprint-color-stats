"""本番の個別精算額を公開記録へ戻さない。"""

import json
import re
from pathlib import Path


def test_公開費用は最終の合計だけで個別精算を復元できない():
    root = Path(__file__).resolve().parents[1] / "bench" / "issue117"
    summary = json.loads((root / "production-summary.json").read_text(encoding="utf-8"))
    accounting = summary["accounting"]
    allowed = {"0", "1", "50"} | {
        str(value / 1_000_000_000)
        for value in (accounting["usage_nusd"], accounting["upper_bound_nusd"],
                      summary["booked_nusd"])
    }
    document = (root / "production-results.md").read_text(encoding="utf-8")
    amounts = re.findall(r"(?<![\d.])(\d+(?:\.\d+)?) USD", document)
    assert set(amounts) <= allowed, "途中の個別精算額はprivateに置き、最終合計だけを公開します"
    assert accounting["upper_bound_calls"] >= 3
