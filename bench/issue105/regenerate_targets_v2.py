"""訂正後の全組合せ不足から、集中上限を変えず層の枠・優先度を再生成する。"""

import argparse
import json
import math
import re
from pathlib import Path

import yaml


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--deficits", type=Path, required=True)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    deficits = json.loads(args.deficits.read_text())
    assert report["snapshot_id"] == deficits["snapshot_id"]
    original = args.targets.read_text(encoding="utf-8")
    config = yaml.safe_load(original)
    layers = {s["id"]: s for s in report["strata"]}
    primary = {r["stratum"]: r for r in deficits["rows"] if r["scope"] == "stratum"
               and r["kind"] == "palette" and r["parts"] == [
                   "wall" if r["conditions"]["domain"] == "real_building" else "tree"]}
    floors = {key: math.ceil(s["intended"]["asset_rows"] / 5) for key, s in layers.items()}
    scores = {key: max(1., 30 - min(r["subject_count"], r["effective_sample_size"]))
              for key, r in primary.items()}
    available = config["image_budget"] // 5 - sum(floors.values())
    exact = {key: available * score / sum(scores.values()) for key, score in scores.items()}
    units = {key: int(v) for key, v in exact.items()}
    for key in sorted(units, key=lambda k: (-(exact[k] - units[k]), k))[
            :available - sum(units.values())]:
        units[key] += 1
    result = []
    text = original.replace("evidence: bench/issue105/results.md",
                            "evidence: bench/issue105/correction-v2/results.md").replace(
                                "deficits: bench/issue105/deficits-after.json",
                                "deficits: bench/issue105/correction-v2/deficits-after.json")
    for layer in config["strata"]:
        key = layer["id"]
        row = primary[key]
        mass = layers[key]["inferred"]["subject_mass"]
        count, effective = row["subject_count"], row["effective_sample_size"]
        priority = 1 if min(count, effective, mass) < 10 else 3 if min(
            count, effective, mass) >= 30 else 2
        images = 5 * (floors[key] + units[key])
        relation_rows = [r for r in deficits["rows"] if r["stratum"] == key
                         and r["kind"] == "relation"]
        gap = {"subjects_to_30": row["subject_deficit_30"],
               "n_eff_to_30": round(row["n_eff_deficit_30"], 6),
               "unvalidated_pairs": sum(not r["model_validated"] for r in relation_rows)}
        pattern = rf"(?ms)(  - id: {re.escape(key)}\n)(.*?)(?=^  - id: |\Z)"
        match = re.search(pattern, text)
        block = re.sub(r"(?m)^    priority: \d+$", f"    priority: {priority}", match[2])
        block = re.sub(r"(?m)^    images: \d+$", f"    images: {images}", block)
        parts = [r["parts"][0] for r in deficits["rows"] if r["stratum"] == key
                 and r["kind"] == "palette"]
        aliases = {"rock": ["rock_face", "rock_scree"], "grass": ["ground_grass"],
                   "snow": ["snow_ice"], "window": ["window_frame", "window_glass"]}
        focus = [part for old in layer["focus_parts"] for part in aliases.get(old, [old])]
        assert set(focus) <= set(parts)
        block = re.sub(r"(?m)^    focus_parts: .*", "    focus_parts: " +
                       yaml.safe_dump(focus, default_flow_style=True, width=1000).strip(), block)
        block = re.sub(r"(?m)^    support_gap: .*\n", "", block)
        gap_line = "    support_gap: " + yaml.safe_dump(
            gap, default_flow_style=True, width=1000).strip()
        block = re.sub(r"(?m)^    priority: \d+$", f"    priority: {priority}\n{gap_line}", block)
        text = text[:match.start(2)] + block + text[match.end(2):]
        result.append({"id": key, "old_images": layer["images"], "images": images,
                       "priority": priority, "gap": gap})
    regenerated = yaml.safe_load(text)
    assert regenerated["limits"] == config["limits"]
    assert sum(s["images"] for s in regenerated["strata"]) == config["image_budget"]
    assert [(s["id"], s["attributes"], s["subjects"]) for s in regenerated["strata"]] == [
        (s["id"], s["attributes"], s["subjects"]) for s in config["strata"]]
    args.targets.write_text(text, encoding="utf-8")
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump({"snapshot_id": deficits["snapshot_id"],
                   "basis": ("既存の意図層画像数を5枚単位で切上げ、"
                             "残枠を主要役割の30支持不足率で配分"),
                   "limits_unchanged": True, "layers": result},
                  stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
