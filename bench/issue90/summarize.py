"""保存した100枠の成否と対応比較を集計し、再実行用の固定入力を残す。"""

import argparse
import hashlib
import json
import platform
import sys
from collections import Counter
from importlib.metadata import distributions
from pathlib import Path
from statistics import mean, median


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = json.loads((args.root / "manifest.json").read_text())
    installed = {dist.metadata["Name"].casefold(): dist.version for dist in distributions()}
    summary = {
        "fixed_slots": len(rows), "status": dict(Counter(row["status"] for row in rows)),
        "budget": json.loads((args.root / "budget.json").read_text()), "arms": {},
        "runtime": {
            "python": sys.version, "platform": platform.platform(),
            "packages": {name: installed.get(name) for name in (
                "torch", "torchvision", "transformers", "pillow", "numpy", "imagehash",
                "colour-science", "opencv-python-headless",
            )},
        },
    }
    for name in ("original-1.0", "thumbnail-1.0", "original-0.5", "thumbnail-0.5"):
        arms = [row["arms"][name] for row in rows if name in row.get("arms", {})]
        good = [arm for arm in arms if arm["status"] == "ok"]
        event_totals = Counter()
        verified_sha1 = 0
        for row in rows:
            arm = row.get("arms", {}).get(name, {})
            if arm.get("status") == "ok" and name.startswith("original"):
                with Path(arm["path"]).open("rb") as stream:
                    actual = hashlib.file_digest(stream, "sha1").hexdigest()
                verified_sha1 += actual == row["candidate"]["rendition"]["original"]["sha1"]
        for arm in arms:
            for event in arm["events"]:
                if isinstance(event["value"], (int, float)):
                    event_totals[event["event"]] += event["value"]
        summary["arms"][name] = {
            "attempted": len(arms), "succeeded": len(good), "failed": len(arms) - len(good),
            "bytes": sum(arm.get("bytes", 0) for arm in good),
            "elapsed_seconds": sum(arm["elapsed_seconds"] for arm in arms),
            "events": dict(event_totals), "verified_original_sha1": verified_sha1,
        }
    pairs = [row["comparison"] for row in rows if "comparison" in row]
    paired = [row for row in rows if all(
        row.get("arms", {}).get(name, {}).get("status") == "ok"
        for name in ("original-1.0", "thumbnail-1.0")
    )]
    summary["paired_file_bytes"] = {
        mode: sum(row["arms"][mode + "-1.0"]["bytes"] for row in paired)
        for mode in ("original", "thumbnail")
    }
    summary["existing_originals"] = sum(
        row["arms"]["original-1.0"].get("acquisition") == "existing_read_only"
        for row in rows if "original-1.0" in row.get("arms", {})
    )
    summary["reused_pairs"] = sum(
        row.get("arms", {}).get("thumbnail-1.0", {}).get("acquisition") == "preserved_previous14"
        for row in rows
    )
    summary["different_sha_pairs"] = sum(
        row["arms"]["original-1.0"].get("sha256")
        != row["arms"]["thumbnail-1.0"].get("sha256")
        for row in rows if row.get("arms", {}).get("thumbnail-1.0", {}).get("status") == "ok"
    )
    summary["quality"] = {"evaluated": len(pairs), "unevaluated": len(rows) - len(pairs),
                          "flag_flips": dict(Counter(k for p in pairs for k in p["flag_flips"]))}
    for key in ("phash_distance", "dominant_oklab_distance", "weighted_oklab_distance"):
        values = [pair[key] for pair in pairs]
        summary["quality"][key] = {
            "mean": mean(values) if values else None, "median": median(values) if values else None,
            "max": max(values) if values else None,
        }
    for group in ("major", "detail"):
        masks = [mask for pair in pairs for mask in pair["mask_agreement"].values()
                 if mask["group"] == group]
        intersection, union = (
            sum(mask[key] for mask in masks) for key in ("intersection", "union")
        )
        summary["quality"][f"{group}_agreement"] = {
            "label_pairs": len(masks), "intersection": intersection, "union": union,
            "value": intersection / union if union else None,
        }
    summary["analysis_errors"] = [
        {"index": row["index"], **row["analysis_error"]} for row in rows if "analysis_error" in row
    ]
    args.output.mkdir(parents=True, exist_ok=True)
    for name, value in (
        ("summary.json", summary),
        ("fixed-input.json", [{k: row[k] for k in ("index", "query", "candidate", "status")
                               if k in row}
                              for row in rows]),
        ("comparison.json", [{k: v for k, v in row.items() if k != "candidate"} for row in rows]),
    ):
        (args.output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
