"""既知110枚の回帰評価。個別所見は私有入力・出力に限定する。"""

import argparse
import base64
import io
import re
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw


def contact_sheet(html, output):
    """既存提示画像を番号順の一覧にする。新たな外部取得はしない。"""
    images = re.findall(r'<img[^>]+src="data:image/[^;]+;base64,([^"]+)"',
                        Path(html).read_text(encoding="utf-8"))
    assert len(images) == 110
    for start in range(0, len(images), 30):
        sheet = Image.new("RGB", (1200, 6 * 155), "white")
        draw = ImageDraw.Draw(sheet)
        for index, value in enumerate(images[start:start + 30]):
            image = Image.open(io.BytesIO(base64.b64decode(value))).convert("RGB")
            image.thumbnail((235, 130))
            x, y = index % 5 * 240, index // 5 * 155
            sheet.paste(image, (x, y + 20))
            draw.text((x + 5, y + 2), str(start + index + 1), fill="black")
        sheet.save(Path(output) / f"contact-{start + 1}.jpg")


def counts(rows, category, field, bad):
    """既知正例・問題報告なしの負例を計数し、他所見のみの真値は不明に残す。"""
    result = Counter(tp=0, fp=0, fn=0, tn=0, unknown_truth=0, unknown_prediction=0)
    for row in rows:
        if category == "aerial_view":
            truth = row["aerial_truth"]
        else:
            labels = row["human_categories"]
            truth = True if category in labels else False if not labels else None
            if category == "real_people" and "depicted_people" in labels:
                truth = False
        if truth is None:
            result["unknown_truth"] += 1
            continue
        value = (row.get("v2_observation") or {}).get(field)
        if value is None or value == "uncertain":
            result["unknown_prediction"] += 1
            continue
        positive = value == bad
        result[("tp" if positive else "fn") if truth else ("fp" if positive else "tn")] += 1
    return dict(result)


def summarize(rows):
    """既知標本の属性単体・採用漏れと群別分母を返す。独立保証には使わない。"""
    groups = {}
    for group in ("old", "new", "challenge"):
        selected = [row for row in rows if (
            "challenge" if row["group"] == "challenge" else row["cohort"]) == group]
        groups[group] = {
            "reviewed": len(selected),
            "accepted_rate": (sum(row["v2_verdict"]["decision"] == "accepted" for row in selected)
                              / len(selected) if selected else None),
            "verdicts": dict(Counter(row["v2_verdict"]["decision"] for row in selected)),
            "accepted_reported_problems": sum(bool(row["human_categories"])
                                              and row["v2_verdict"]["decision"] == "accepted"
                                              for row in selected),
            "attributes": {category: counts(selected, category, field, bad)
                           for category, field, bad in (
                               ("non_target", "target", False),
                               ("black_and_white", "black_and_white", True),
                               ("real_people", "real_people", "present"),
                               ("aerial_view", "aerial_view", True))},
        }
    unavailable = sum(row.get("v2_observation") is None for row in rows)
    expected_holds = sum(
        row.get("v2_observation") is None
        and row["v2_verdict"].get("reason") == "input_hold"
        and row.get("image_gate_run_id") is None
        and (row.get("image_gate_verdict") or {}).get("reason") == "gate_enqueue_failed"
        for row in rows)
    return {"groups": groups, "independent_evaluation": False,
            "prediction_coverage": {"total": len(rows), "observed": len(rows) - unavailable,
                                    "expected_input_holds": expected_holds,
                                    "unexpected_unavailable": unavailable - expected_holds},
            "low_saturation_color": {
                "reviewed": sum(row["low_saturation_color"] for row in rows),
                "black_and_white_false_positive": sum(
                    row["low_saturation_color"]
                    and (row.get("v2_observation") or {}).get("black_and_white") is True
                    for row in rows)},
            "known_black_and_white": {
                "positive": sum("black_and_white" in row["human_categories"] for row in rows),
                "missed_or_unknown": sum("black_and_white" in row["human_categories"]
                                         and (row.get("v2_observation") or {}).get(
                                             "black_and_white") is not True for row in rows)},
            "aerial_adopted": sum(row["aerial_truth"] is True
                                  and row["v2_verdict"]["decision"] == "accepted" for row in rows)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("html")
    parser.add_argument("output")
    args = parser.parse_args()
    contact_sheet(args.html, args.output)
