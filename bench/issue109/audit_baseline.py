"""#90の固定100枠を再取得・再解析せず、#109の許容差で監査する。"""

import hashlib
import json
from pathlib import Path

from colorstats.collect.quality import audit

root = Path(__file__).resolve().parents[2]
source = root / "bench/issue90/existing100/comparison.json"
result = {
    "input": str(source.relative_to(root)),
    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    **audit(json.loads(source.read_text(encoding="utf-8"))),
}
(Path(__file__).parent / "baseline-audit.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
)
print(json.dumps(result, ensure_ascii=False))
