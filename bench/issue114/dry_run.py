"""保存済みREAD ONLY集計から収集枠を計算する。DB接続・通信・ジョブ投入は行わない。"""

import json
import math
from collections import Counter
from decimal import Decimal
from pathlib import Path

from colorstats.collect.coverage import matches
from colorstats.collect.targets import load_targets

ROOT = Path(__file__).resolve().parents[2]


def main():
    config = load_targets(ROOT / "configs/collection_targets.yaml", ROOT / "taxonomy")
    snapshot = json.loads((Path(__file__).parent / "db-snapshot.json").read_text())
    budget, limits = config["image_budget"], config["limits"]
    def cap(value, share):
        return int(Decimal(str(share)) * value)

    counts = Counter()
    for group in snapshot["groups"]:
        counts[group["source"]] += group["count"]
    layers = []
    for layer in config["strata"]:
        groups = [g for g in snapshot["groups"] if matches(g["attributes"], layer)]
        sources = Counter()
        for group in groups:
            sources[group["source"]] += group["count"]
        subjects = sum(
            g["subjects"] for g in snapshot["subjects"] if matches(g["attributes"], layer)
        )
        remaining = max(0, layer["images"] - sum(sources.values()))
        if subjects >= layer["subjects"]:
            remaining = 0
        source_cap = cap(layer["images"], limits["source_share"])
        layers.append({
            "stratum": layer["id"], "priority": layer["priority"],
            "target_images": layer["images"], "current_images": sum(sources.values()),
            "current_subjects": subjects, "target_subjects": layer["subjects"],
            "remaining_images": remaining, "provider_cap": source_cap,
            "author_cap": cap(layer["images"], limits["author_share"]),
            "commons_additional": min(
                remaining, max(0, source_cap - sources["wikimedia_commons"]),
            ),
            "openverse_additional": min(remaining, max(0, source_cap - sources["openverse"])),
        })
    remaining = max(0, budget - sum(counts.values()))
    source_cap = cap(budget, limits["source_share"])
    additional = {
        source: min(
            remaining, max(0, source_cap - counts[source]),
            sum(layer[key] for layer in layers),
        )
        for source, key in (
            ("wikimedia_commons", "commons_additional"), ("openverse", "openverse_additional"),
        )
    }
    result = {
        "captured_at": snapshot["captured_at"], "image_budget": budget,
        "current_sources": dict(counts), "remaining_images": remaining,
        "unassigned_images": snapshot["asset_count"] - sum(
            layer["current_images"] for layer in layers
        ),
        "pending_images": snapshot["pending_count"], "limits": limits,
        "provider_cap": source_cap, "author_cap": cap(budget, limits["author_share"]),
        "region_cap": cap(budget, limits["region_share"]),
        "subject_cap": min(limits["subject_images"], cap(budget, limits["subject_share"])),
        "single_provider_additional_upper_bounds": additional,
        "minimum_other_images_for_30000": budget - source_cap,
        "layers": layers,
    }
    estimates = []
    for yield_rate in (1, 0.1, 0.01):
        for target in (6000, additional["openverse"]):
            searches = math.ceil(Decimal(target) / (10 * Decimal(str(yield_rate))))
            estimates.append({
                "openverse_additional": target, "assumed_yield": yield_rate,
                "search_requests": searches,
                "anonymous_daily_quota_days": math.ceil(searches / 100),
                "standard_api_requests_with_token_per_job": 2 * searches,
                "standard_daily_quota_days": math.ceil(2 * searches / 10000),
            })
    result["rate_estimates"] = estimates
    (Path(__file__).parent / "dry-run.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps({k: v for k, v in result.items() if k != "layers"}, ensure_ascii=False))
    for layer in layers:
        print(" | ".join(str(layer[k]) for k in (
            "stratum", "current_images", "current_subjects", "target_images", "provider_cap",
            "commons_additional", "openverse_additional", "author_cap",
        )))


if __name__ == "__main__":
    main()
