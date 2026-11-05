"""決定的50画像の目視・保存説明・EXIF照合結果。画像と個別出典は公開しない。"""

import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    rows = json.loads(raw)
    assert len(rows) == 50 and len({r["sha256"] for r in rows}) == 50
    assert rows == sorted(rows, key=lambda r: hashlib.sha256(
        ("issue105-category-audit-v2:" + r["sha256"]).encode()).hexdigest())
    errors = {27: "実景ではなく冬景色の絵画", 29: "橋の画像は昼明かり・GPS太陽高度もnight外",
              49: "実景ではなく秋の森林の絵画"}
    uncertain = {24: "青い空の薄明とnightの境界。UTC根拠なし",
                 47: "青い空の薄明とnightの境界。UTC・GPS根拠なし"}
    result = {
        "seed": "issue105-category-audit-v2:", "input_sha256": hashlib.sha256(raw).hexdigest(),
        "sampling": "旧#105のカテゴリ起因150画像からSHA重複を除きseed+SHAのhash順で50件",
        "checks": ["実景写真か", "カテゴリが描写対象に適用されるか",
                   "季節・時間帯と可視情報の明白な矛盾がないか", "保存説明・EXIFと整合するか"],
        "sample_size": 50, "confirmed_errors": len(errors),
        "error_rate": len(errors) / 50, "uncertain": len(uncertain),
        "visually_consistent": 50 - len(errors) - len(uncertain),
        "interpretation": ("目視で確認した誤り3/50=6%。保留2件を正解として扱わない。"
                           "母集団精度の保証ではない"),
        "rows": [{"index": i, "status": "error" if i in errors else "uncertain"
                  if i in uncertain else "consistent",
                  "reason": errors.get(i) or uncertain.get(i) or "描写・保存情報に明白な矛盾なし"}
                 for i in range(1, 51)],
    }
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
