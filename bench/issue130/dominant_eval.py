"""支配色の条件固定、調整選定後の確認評価。同じ画像でv2の壁平均と比較する。"""

import argparse
from collections import Counter
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from time import monotonic

import cv2
import numpy as np
from bench.issue73.evaluate import digest, read, write
from bench.issue81.evaluate import text_digest
from PIL import Image

from colorstats.analyze import dominant_wall, region_policy, visible_wall
from colorstats.analyze.segment import _digest
from colorstats.colors import rgb_to_oklab

VERSION = "issue130-dominant-color-eval-v3"
CANDIDATES = [{"front": front, "clusters": k} for front in (
    "oneformer_building", "raw_wall_union") for k in (2, 3, 5)]
FILES = ("bench/issue130/dominant-plan.md", "bench/issue130/dominant_eval.py",
         "src/colorstats/analyze/dominant_wall.py", "src/colorstats/analyze/color.py",
         "src/colorstats/colors.py", "bench/issue73/plan.json")


def summarize(rows):
    errors = [row["delta_ok"] for row in rows if row["delta_ok"] is not None]
    missing = len(rows) - len(errors)
    return {"images": len(rows), "valid": len(errors), "missing": missing,
            "missing_rate": missing / len(rows) if rows else None,
            "missing_reasons": dict(Counter(row["missing_reason"] for row in rows
                                             if row["delta_ok"] is None)),
            "median": float(np.median(errors)) if errors else None,
            "p90": float(np.quantile(errors, 0.90, method="linear")) if errors else None}


def choose(reports):
    eligible = [i for i, row in enumerate(reports) if row["valid"] and row["missing_rate"] <= 0.20]
    if eligible:
        selected = min(eligible, key=lambda i: (reports[i]["median"], reports[i]["p90"],
                                              reports[i]["missing_rate"], i))
    else:
        selected = min(range(len(reports)), key=lambda i: (
            reports[i]["missing_rate"],
            reports[i]["median"] if reports[i]["valid"] else float("inf"),
            reports[i]["p90"] if reports[i]["valid"] else float("inf"), i))
    return selected, bool(eligible)


def freeze(args):
    previous = read(args.previous)
    if digest(args.previous) != "e4c151e861ae57e225a0a50c87a1903f1e3410b825524861c2a8d46c34ad26b9":
        raise ValueError("v2の固定入力台帳が不一致です")
    args.output.mkdir(parents=True, mode=0o700, exist_ok=False)
    rows = []
    for row in previous["inputs"]:
        if row["dataset"] != "cmp":
            continue
        path = args.inputs / row["file"]
        if digest(path) != row["sha256"]:
            raise ValueError("RGB・GT・候補・semanticの固定npzが不一致です")
        policy_path = args.baseline / Path(row["file"]).stem / "policy.json"
        policy = read(policy_path)
        if policy["version"] != visible_wall.VERSION:
            raise ValueError("現行基準の壁mask版が不一致です")
        record = policy["roles"][visible_wall.WALL]
        if digest(Path(record["path"])) != record["sha256"]:
            raise ValueError("現行基準の壁mask SHAが不一致です")
        rows.append({**row, "baseline": record, "baseline_policy_sha256": digest(policy_path)})
    if Counter(row["split"] for row in rows) != {"tune": 324, "holdout": 282}:
        raise ValueError("CMPの旧分割が不一致です")
    spec = {"version": VERSION, "base_commit": "d044825", "seed": 73,
            "files": {name: text_digest(Path(name)) for name in FILES}, "rows": rows,
            "input_manifest_sha256": _digest(rows), "candidates": CANDIDATES,
            "gates": {"median_delta_ok_max": 0.02, "missing_rate_max": 0.20},
            "truth": "CMP ID2全画素のOKLab算術平均・黒白保持",
            "prediction": "正面のOKLab k-means最大クラスタの画素平均・同面積は欠測",
            "baseline": "visible-wall-policy-v2 ubuntu-2の有効壁mask平均",
            "kmeans": {"seed": 0, "attempts": 1, "max_iter": 100, "epsilon": 1e-6,
                       "initialization": "k-means++", "clip_extremes": False, "threads": 1},
            "versions": {name: version(name) for name in (
                "numpy", "Pillow", "colour-science", "opencv-python-headless")},
            "frozen_at": datetime.now(UTC).isoformat(), "before_predictions": True,
            "independent_blind_confirmation": False}
    write(args.output / "freeze.json", spec)
    public = {key: value for key, value in spec.items() if key != "rows"}
    public.update(freeze_sha256=digest(args.output / "freeze.json"), images=606,
                  split_counts={"tune": 324, "holdout": 282})
    write(args.output / "freeze-public.json", public)


def verify(spec):
    for path, sha in spec["files"].items():
        if text_digest(Path(path)) != sha:
            raise ValueError("予測前の固定後に仕様・実装が変わっています")
    if spec["candidates"] != CANDIDATES or any(version(name) != value
                                              for name, value in spec["versions"].items()):
        raise ValueError("固定候補または実行ライブラリ版が不一致です")


def front_mask(sample, kind):
    if kind == "oneformer_building":
        return sample["semantic"] == 1
    mask = np.zeros(sample["truth"].shape, dtype=bool)
    for label, array, confidence in zip(sample["labels"], sample["masks"], sample["scores"],
                                        strict=True):
        if region_policy.PARENTS.get(str(label)) == visible_wall.WALL and confidence > 0.35:
            mask |= array
    return mask


def run(args):
    spec = read(args.freeze)
    verify(spec)
    cv2.setNumThreads(1)
    args.output.mkdir(parents=True, mode=0o700, exist_ok=False)
    started = monotonic()
    tune = [[] for _ in CANDIDATES]
    holdout, baseline, private = [], [], []
    selected = None
    for split in ("tune", "holdout"):
        count = 0
        for row in spec["rows"]:
            if row["split"] != split:
                continue
            path = args.inputs / row["file"]
            if digest(path) != row["sha256"]:
                raise ValueError("固定入力のSHAが不一致です")
            with np.load(path, allow_pickle=False) as sample:
                rgb, truth = sample["rgb"], sample["truth"]
                lab = rgb_to_oklab(rgb.astype(np.float64) / 255)
                gt = lab[truth == 2].mean(axis=0) if (truth == 2).any() else None
                image = Image.fromarray(rgb)
                indexes = range(len(CANDIDATES)) if split == "tune" else [selected]
                for index in indexes:
                    candidate = CANDIDATES[index]
                    prediction = dominant_wall.estimate(
                        image, front_mask(sample, candidate["front"]),
                        clusters=candidate["clusters"])
                    error = float(np.linalg.norm(np.array(prediction["color"]) - gt)) if (
                        prediction["color"] is not None and gt is not None) else None
                    result = {"delta_ok": error, "missing_reason": "gt_missing" if gt is None
                              else prediction["missing_reason"]}
                    (tune[index] if split == "tune" else holdout).append(result)
                    private.append({"file": row["file"], "split": split, "candidate": index,
                                    "gt": gt.tolist() if gt is not None else None,
                                    "prediction": prediction, **result})
                if split == "holdout":
                    record = row["baseline"]
                    if digest(Path(record["path"])) != record["sha256"]:
                        raise ValueError("基準mask SHAが不一致です")
                    mask = np.array(Image.open(record["path"])) != 0
                    if mask.shape != truth.shape:
                        raise ValueError("基準mask座標が不一致です")
                    color = lab[mask].mean(axis=0) if mask.any() else None
                    error = float(np.linalg.norm(color - gt)) if (
                        color is not None and gt is not None) else None
                    baseline.append({"delta_ok": error, "missing_reason": "wall_mask_missing"
                                     if color is None else "gt_missing" if gt is None else None})
                    private[-1]["baseline_color"] = color.tolist() if color is not None else None
                    private[-1]["baseline_delta_ok"] = error
            count += 1
            if count % 50 == 0:
                print({"split": split, "images": count, "seconds": monotonic() - started},
                      flush=True)
        if split == "tune":
            reports = [summarize(values) for values in tune]
            selected, eligible = choose(reports)
            write(args.output / "selection.json", {"freeze_sha256": digest(args.freeze),
                  "selected": CANDIDATES[selected], "index": selected, "tune": reports,
                  "eligible_candidate_exists": eligible, "before_holdout_predictions": True,
                  "frozen_at": datetime.now(UTC).isoformat()})
            verify(spec)
    result = summarize(holdout)
    paired = [(a, b) for a, b in zip(holdout, baseline, strict=True)
              if a["delta_ok"] is not None and b["delta_ok"] is not None]
    passed = (result["valid"] > 0 and result["median"] <= spec["gates"]["median_delta_ok_max"]
              and result["missing_rate"] <= spec["gates"]["missing_rate_max"])
    write(args.output / "private.json", private)
    write(args.output / "summary.json", {
        "version": VERSION, "freeze_sha256": digest(args.freeze),
        "selection_sha256": digest(args.output / "selection.json"),
        "selected": CANDIDATES[selected], "status": "passed" if passed else "failed",
        "gates": spec["gates"], "holdout": result, "baseline": summarize(baseline),
        "paired": {"images": len(paired), "prediction": summarize([a for a, _ in paired]),
                   "baseline": summarize([b for _, b in paired])},
        "seconds": monotonic() - started, "opencv_threads": 1, "new_gpu_predictions": 0,
        "pr_relation": "Closes #130" if passed else "Refs #130",
        "production_statistics_changed": False, "independent_blind_confirmation": False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "run"))
    for name in ("inputs", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("previous", "baseline", "freeze"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    if args.action == "freeze":
        freeze(args)
    else:
        run(args)


if __name__ == "__main__":
    main()
