"""固定100候補の原本・API縮小を対応比較する。画像と失敗履歴は削除しない。"""

import argparse
import copy
import hashlib
import json
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import imagehash
import numpy as np
from PIL import Image

from colorstats.analyze import color, prep, segment
from colorstats.collect import Candidate, SearchRequest
from colorstats.collect.commons import CommonsAdapter
from colorstats.collect.http import MeasurementLimit
from colorstats.collect.policy import load_policy
from colorstats.queue import Claim

QUERIES = [
    "Japanese castle", "Gothic cathedral facade", "skyscraper vertical",
    "building architectural ornament", "building backlit sunset",
    "mountain landscape", "waterfall vertical", "canyon landscape",
    "rock formation detail", "forest backlight",
]
PROMPTS = {
    "wall_main": "building wall", "roof_surface": "roof", "window_frame": "window frame",
    "column": "column", "cornice": "cornice", "relief": "carved relief",
    "rock_face": "rock", "water": "water", "vegetation_low": "vegetation",
    "ground_soil": "ground",
}
DETAIL = {"window_frame", "column", "cornice", "relief"}


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


def claim(stage, payload, digest=""):
    identifier = uuid4()
    return Claim(identifier, identifier, stage, identifier, digest, payload, 1, datetime.now(UTC))


def publish(prepared):
    for temporary, target in prepared.files:
        if target.exists():
            raise FileExistsError(target)
        temporary.replace(target)


def acquire(root, policy_path, frozen=None):
    budget_path = root / "budget.json"
    budget = {"limits": {"api": 120, "original": 30, "thumbnail": 30},
              "used": {"api": 0, "original": 0, "thumbnail": 0},
              "created_at": datetime.now(UTC).isoformat(), "base_commit": "d97c218",
              "queries": QUERIES, "intervals": [1.0, 0.5], "paired_images": 15}
    if budget_path.exists():
        budget = json.loads(budget_path.read_text())
    save(budget_path, budget)
    if (root / "manifest.json").exists() and any(
        row.get("arms") for row in json.loads((root / "manifest.json").read_text())
    ):
        raise FileExistsError("取得済みarmは再取得・上書きしません。解析だけを再開してください")
    policy = load_policy(policy_path, "wikimedia_commons")
    adapter = CommonsAdapter(policy)
    mode = "api"
    events = []

    def observe(event, value=1):
        if event in {"api_request", "request"}:
            key = "api" if event == "api_request" else mode
            if budget["used"][key] >= budget["limits"][key]:
                raise MeasurementLimit(key)
            budget["used"][key] += 1
            save(budget_path, budget)
        if event not in {"search", "candidate"}:
            events.append({"event": event, "value": value})

    adapter.observer = observe
    groups = (
        json.loads((root / "search.json").read_text()) if (root / "search.json").exists() else []
    )
    for query in ([] if frozen else QUERIES[len(groups):]):
        try:
            result = adapter.search(SearchRequest(
                "wikimedia_commons", query, download_mode="thumbnail",
            ))
        except json.JSONDecodeError as error:
            (root / "api-invalid-response.txt").write_text(error.doc, encoding="utf-8")
            raise
        groups.append([{"query": query, "candidate": asdict(c)} for c in result.candidates])
        save(root / "search.json", groups)
    rows = json.loads(frozen.read_text()) if frozen else [
        group[index] for index in range(10) for group in groups if index < len(group)
    ]
    if not frozen:
        for query, group in zip(QUERIES, groups, strict=True):
            ranks = {row["candidate"]["rank"] for row in group}
            rows.extend({"query": query, "search_rank": rank, "status": "search_missing"}
                        for rank in range(10) if rank not in ranks)
    rows = rows[:100]
    while len(rows) < 100:
        rows.append({"status": "search_missing"})
    for index, row in enumerate(rows):
        row["index"] = index
        row["status"] = (
            "budget_not_evaluated" if index >= 15 else "pending"
        ) if "candidate" in row else "search_missing"
    save(root / "manifest.json", rows)
    save(root / "api-events.json", events)
    adapter.finish()
    for row in rows[:15]:
        candidate = Candidate(**row["candidate"])
        if candidate.exclusion_reason:
            row["status"] = candidate.exclusion_reason
            continue
        row["arms"] = {}
        for interval in (1.0, 0.5):
            adapter.policy["hosts"]["upload.wikimedia.org"]["min_interval"] = interval
            adapter.policy["hosts"]["thumb.wikimedia.org"]["min_interval"] = interval
            for mode in ("original", "thumbnail"):
                variant = copy.deepcopy(candidate.rendition)
                variant["variant"] = mode
                current = replace(candidate, rendition=variant, download_url=(
                    candidate.download_url if mode == "thumbnail" else None
                ))
                name = f"{mode}-{interval}"
                target = root / f"{row['index']:03d}-{name}.image"
                arm = {"path": str(target), "variant": variant, "interval": interval}
                events.clear()
                started = time.monotonic()
                try:
                    if target.exists():
                        raise FileExistsError(target)
                    adapter.download(current, target)
                    adapter.finish()
                    with target.open("rb") as stream:
                        arm["sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
                    arm.update(status="ok", bytes=target.stat().st_size)
                    if mode == "original":
                        with target.open("rb") as stream:
                            actual = hashlib.file_digest(stream, "sha1").hexdigest()
                        if actual != variant["original"]["sha1"]:
                            raise ValueError("原本revisionのSHA-1が固定入力と一致しません")
                    with Image.open(target) as image:
                        arm.update(width=image.width, height=image.height,
                                   mime=Image.MIME[image.format])
                except Exception as error:
                    arm.update(status="failed", error=type(error).__name__, message=str(error))
                arm.update(elapsed_seconds=time.monotonic() - started, events=list(events))
                row["arms"][name] = arm
                save(root / "manifest.json", rows)
        row["status"] = "acquired" if all(
            arm["status"] == "ok" for arm in row["arms"].values()
        ) else "acquisition_failed"
        save(root / "manifest.json", rows)
    adapter.finish()
    save(root / "manifest.json", rows)
    return rows


def analyze(root, models, analysis_id):
    rows = json.loads((root / "manifest.json").read_text())
    for row in rows:
        if "comparison" in row:
            continue
        arms = row.get("arms", {})
        pair = [arms.get(f"{mode}-1.0", {}) for mode in ("original", "thumbnail")]
        if not all(arm.get("status") == "ok" for arm in pair):
            continue
        if "analysis_error" in row:
            row.setdefault("analysis_failures", []).append(row.pop("analysis_error"))
        results = []
        for mode, arm in zip(("original", "thumbnail"), pair, strict=True):
            directory = root / f"{analysis_id}-{row['index']:03d}-{mode}"
            directory.mkdir(exist_ok=True)
            try:
                payload = {"input_path": arm["path"], "derived_path": str(directory / "prep.jpg"),
                           "license_class": "open", "taxonomy_version": "0.1.0",
                           "rendition": arm["variant"]}
                if (directory / "prep.jpg").exists():
                    inspected = prep._inspect(Path(arm["path"]))
                    quality, phash = prep._quality(inspected), inspected["phash"]
                else:
                    prepared = prep.prepare(claim("prep", payload))
                    save(directory / "prep-parameters.json", prepared.info.parameters)
                    quality = prep._quality(prepared.data)
                    phash = prepared.data["phash"]
                    publish(prepared)
                payload = {
                    "input_path": str(directory / "prep.jpg"),
                    "output_path": str(directory / "segment.json"),
                    "method": "sam2-dino", "model_paths": {
                        name: str(models / name) for name in ("sam2", "dino")
                    }, "prompts": PROMPTS, "threshold": 0.35, "text_threshold": 0.25,
                    "license_class": "open", "taxonomy_version": "0.1.0",
                    "rendition": arm["variant"],
                }
                if (directory / "segment.json").exists():
                    segmented = json.loads((directory / "segment.json").read_text())
                else:
                    prepared = segment.prepare(claim(
                        "segment", payload, segment.config_hash(payload),
                    ))
                    save(directory / "segment-parameters.json", prepared.info.parameters)
                    publish(prepared)
                    segmented = prepared.data
                masks = {}
                for region in segmented["regions"]:
                    with Image.open(region["mask_path"]) as mask:
                        pixels = np.asarray(mask) != 0
                    label = region["label"]
                    masks[label] = masks.get(label, np.zeros_like(pixels)) | pixels
                payload = {
                    "input_path": str(directory / "prep.jpg"),
                    "output_path": str(directory / "color.json"), "license_class": "open",
                    "taxonomy_version": "0.1.0", "rendition": arm["variant"],
                }
                if (directory / "color.json").exists():
                    observations = json.loads(
                        (directory / "color.json").read_text(),
                    )["observations"]
                else:
                    prepared = color.prepare(claim("color", payload, color.config_hash(payload)))
                    save(directory / "color-parameters.json", {
                        **prepared.info.parameters, "rendition": arm["variant"],
                    })
                    publish(prepared)
                    observations = prepared.data["observations"]
                dominant = observations[0]["observed_oklab"]["dominant"]
                centroid = sum(
                    observation["area_ratio"] * np.asarray(
                        observation["observed_oklab"]["dominant"],
                    ) for observation in observations
                )
                results.append({"phash": phash, "quality": quality, "dominant": dominant,
                                "centroid": centroid,
                                "masks": masks})
            except Exception as error:
                row["analysis_error"] = {"mode": mode, "error": type(error).__name__,
                                         "message": str(error)}
                break
        if len(results) == 2:
            a, b = results
            agreements = {}
            for label in sorted(a["masks"].keys() | b["masks"].keys()):
                ma, mb = a["masks"].get(label), b["masks"].get(label)
                if ma is None:
                    ma = np.zeros_like(mb)
                if mb is None:
                    mb = np.zeros_like(ma)
                if ma.shape != mb.shape:
                    mb = np.asarray(Image.fromarray(mb).resize(
                        (ma.shape[1], ma.shape[0]), Image.Resampling.NEAREST,
                    ))
                union = int((ma | mb).sum())
                agreements[label] = {"intersection": int((ma & mb).sum()), "union": union,
                                     "agreement": int((ma & mb).sum()) / union if union else None,
                                     "group": "detail" if label in DETAIL else "major"}
            row["comparison"] = {
                "phash_distance": int(
                    imagehash.hex_to_hash(a["phash"]) - imagehash.hex_to_hash(b["phash"])
                ),
                "quality": [a["quality"], b["quality"]],
                "flag_flips": [k for k in a["quality"] if isinstance(a["quality"][k], bool)
                               and a["quality"][k] != b["quality"][k]],
                "dominant_oklab_distance": float(np.linalg.norm(
                    np.asarray(a["dominant"]) - b["dominant"],
                )), "weighted_oklab_distance": float(np.linalg.norm(a["centroid"] - b["centroid"])),
                "mask_agreement": agreements, "truth_iou": None,
                "truth_reason": "この固定入力に人手正解なし。一致度は精度ではない",
            }
        save(root / "manifest.json", rows)
    save(root / "results.json", rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=Path("configs/source_policy.yaml"))
    parser.add_argument("--models", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--analysis-id", default="analysis")
    parser.add_argument("--acquire", action="store_true")
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    if args.acquire:
        acquire(args.root, args.policy, args.manifest)
    if args.models:
        with patch.object(segment, "_hash", lru_cache(maxsize=None)(segment._hash)):
            analyze(args.root, args.models, args.analysis_id)


if __name__ == "__main__":
    main()
