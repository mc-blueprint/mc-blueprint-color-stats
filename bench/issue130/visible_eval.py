"""新評価v2の事前固定と、両GPUでの補助部位推論・全非void計数。"""

import argparse
import fcntl
import hashlib
import io
import os
import time
import zipfile
from collections import Counter, defaultdict
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import yaml
from bench.issue73.evaluate import digest, read, truth_for, write
from bench.issue81.evaluate import text_digest
from bench.issue118.smoke import gpu_processes
from bench.issue130.analyze_fp import distribution
from PIL import Image

from colorstats.analyze import region_policy, segment_models, visible_wall
from colorstats.analyze.segment import _digest
from colorstats.colors import rgb_to_oklab

VERSION = "issue130-visible-wall-eval-v2"
FILES = ["bench/issue130/visible-plan.md", "bench/issue130/visible_eval.py",
         "bench/issue130/analyze_fp.py", "bench/issue73/plan.json", "bench/issue81/label-map.yaml",
         "configs/segment_stats.yaml", "src/colorstats/colors.py", "ops/deploy/m3_analysis.py",
         *["src/colorstats/analyze/" + name for name in (
             "visible_wall.py", "region_policy.py", "segment.py", "segment_models.py",
             "region-parents-v2.json")]]


def freeze(args):
    from bench.issue121 import public, quality

    previous = read(args.previous)
    if digest(args.previous) != "6e2b37e65eca4ee08cb12b5ea4fc1828e06f2c353914ec1b004acd49fdd118a2":
        raise ValueError("旧freezeのSHAが一致しません")
    plan = read(Path("bench/issue73/plan.json"))
    args.output.mkdir(parents=True, mode=0o700, exist_ok=False)
    inputs = args.output / "inputs"
    inputs.mkdir()
    manifests = []
    with ExitStack() as stack:
        archives = {}
        for name, sha in previous["archives"].items():
            if digest(args.data / name) != sha:
                raise ValueError("固定ZIPが不一致です")
            archives[name] = stack.enter_context(zipfile.ZipFile(args.data / name))
        for index, row in enumerate(plan["rows"]):
            raw = archives[row["archive"]].read(row["image"])
            annotation = archives[row["archive"]].read(row["annotation"])
            if (hashlib.sha256(raw).hexdigest() != row["sha256"] or hashlib.sha256(
                    annotation).hexdigest() != row["truth_sha256"]):
                raise ValueError("入力・GT SHAが不一致です")
            image = Image.open(io.BytesIO(raw)).convert("RGB")
            image.thumbnail((512, 512), Image.Resampling.LANCZOS)
            if hashlib.sha256(image.tobytes()).hexdigest() != row["resized_rgb_sha256"]:
                raise ValueError("固定RGBが不一致です")
            semantic_path = args.semantic / f"semantic-{index:04d}.png"
            if digest(semantic_path) != previous["semantic_sha256"][index]:
                raise ValueError("semantic SHAが不一致です")
            rows, record = public.cached_predictions(row, args.cache)
            if record["settings"] != plan["source_settings"][row["dataset"]]:
                raise ValueError("候補設定が不一致です")
            semantic = np.array(Image.open(semantic_path))
            masks = np.stack([mask for _, mask, _ in rows]) if rows else np.zeros(
                (0, image.height, image.width), dtype=bool)
            path = inputs / f"{index:04d}.npz"
            np.savez_compressed(path, rgb=np.asarray(image), truth=truth_for(row, archives),
                                semantic=semantic, masks=masks,
                                labels=np.array([label for label, _, _ in rows], dtype="U64"),
                                scores=np.array([score for _, _, score in rows]))
            manifests.append({"file": path.name, "sha256": digest(path),
                              "dataset": row["dataset"], "split": row["split"],
                              "source_sha256": row["sha256"]})
    smoke = []
    for dataset in ("cmp", "ade"):
        candidates = [row for row in manifests if row["dataset"] == dataset
                      and row["split"] == "holdout"]
        candidates.sort(key=lambda row: hashlib.sha256(("13020261108" + row[
            "source_sha256"]).encode()).hexdigest())
        smoke.extend(row["file"] for row in candidates[:3])
    spec = {"version": VERSION, "frozen_at": datetime.now(UTC).isoformat(),
            "definition": visible_wall.configuration()["definition"], "base_commit": "4fe8dfc",
            "files": {name: text_digest(Path(name)) for name in FILES},
            "reference": {name: text_digest(Path(module.__file__)) for name, module in (
                ("public", public), ("quality", quality))}, "inputs": manifests,
            "input_manifest_hash": _digest(manifests), "smoke": smoke, "seed": 73,
            "gates": {"precision": 0.80, "recall": 0.30},
            "policy": visible_wall.configuration(), "policy_hash": visible_wall.policy_hash(),
            "models": previous["models"], "oneformer": previous["legacy_model"],
            "production_prompts": previous["production_prompts"],
            "cached_prompts": previous["cached_prompts"],
            "before_new_predictions": True, "independent_blind_confirmation": False}
    write(args.output / "freeze.json", spec)
    public_spec = {key: value for key, value in spec.items() if key not in ("inputs", "smoke")}
    public_spec.update(freeze_sha256=digest(args.output / "freeze.json"),
                       input_count=len(manifests), smoke_count=len(smoke))
    write(args.output / "freeze-public.json", public_spec)


def verify(spec):
    if spec["policy_hash"] != visible_wall.policy_hash():
        raise ValueError("新policyが固定後に変わっています")
    for name, sha in spec["files"].items():
        if text_digest(Path(name)) != sha:
            raise ValueError("固定コード・仕様が変わっています")
    from bench.issue121 import public, quality

    for name, module in (("public", public), ("quality", quality)):
        if text_digest(Path(module.__file__)) != spec["reference"][name]:
            raise ValueError("参照読取器・指標が変わっています")


def predictions(masks):
    return [("wall_main" if role == visible_wall.WALL else "vegetation_tree_canopy"
             if role == "real_terrain/tree" else role.split("/", 1)[1], mask)
            for role, mask in masks.items()]


def run(args):
    from bench.issue121.quality import aggregate, measure, part_decision

    spec = read(args.freeze)
    verify(spec)
    args.output.mkdir(parents=True, mode=0o700, exist_ok=False)
    lock = args.slot.open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if gpu_processes():
        raise RuntimeError("GPU処理があるため開始しません")
    models = {}
    for name, files in spec["models"].items():
        for filename, sha in files.items():
            if digest(args.models / name / filename) != sha:
                raise ValueError("候補モデルSHAが不一致です")
        models[name] = {"files": files}
    if region_policy.model_configuration(args.models / "oneformer") != spec["oneformer"]:
        raise ValueError("OneFormer SHAが不一致です")
    mapping = yaml.safe_load(Path("bench/issue81/label-map.yaml").read_text("utf-8"))
    totals, colors, diagnostics = defaultdict(list), defaultdict(list), defaultdict(Counter)
    pooled = {key: {"pixels": 0, "sum": np.zeros(3)} for key in ("prediction", "tp", "gt")}
    records, smoke = [], []
    peaks = {"peak_allocated_bytes": 0, "peak_reserved_bytes": 0}
    started = time.monotonic()
    import torch

    from colorstats.queue.core import NonRetryableError

    try:
        for index, row in enumerate(spec["inputs"]):
            if any(pid != os.getpid() for pid, _ in gpu_processes()):
                raise RuntimeError("別のGPU処理を検出しました")
            path = args.inputs / row["file"]
            if digest(path) != row["sha256"]:
                raise ValueError("固定npz SHAが不一致です")
            with np.load(path, allow_pickle=False) as sample:
                rgb, truth, semantic = (sample[key] for key in ("rgb", "truth", "semantic"))
                rows = list(zip(sample["labels"].tolist(), list(sample["masks"]),
                                sample["scores"].tolist(), strict=True))
            dataset, split = row["dataset"], row["split"]
            labels = list(spec["cached_prompts"][dataset])
            extra = []
            if dataset == "cmp":
                extra, runtime = segment_models.predict(
                    Image.fromarray(rgb), "sam2-dino",
                    {name: str(args.models / name) for name in models}, models,
                    visible_wall.EXTRA_PROMPTS, 0.35, 0.25)
                for key in peaks:
                    peaks[key] = max(peaks[key], runtime[key])
                sample_dir = args.output / row["file"].replace(".npz", "")
                sample_dir.mkdir()
                for number, (_, mask, _) in enumerate(extra):
                    target = sample_dir / f"aux-{number}.png"
                    Image.fromarray(mask.astype(np.uint8) * 255).save(target)
                write(sample_dir / "aux.json", [{"label": label, "confidence": score,
                      "file": f"aux-{i}.png", "sha256": digest(sample_dir / f"aux-{i}.png")}
                      for i, (label, _, score) in enumerate(extra)])
            masks, reasons, metrics = visible_wall.constrain(semantic, rows, labels, extra)
            if dataset == "cmp":
                input_path = sample_dir / "input.png"
                Image.fromarray(rgb).save(input_path)
                contract, files = region_policy.save_artifacts(
                    sample_dir / "segment.json", "evaluation-v2", semantic, rows, labels,
                    {"payload": {"method": visible_wall.METHOD},
                     "input_sha256": digest(input_path),
                     "models": {"oneformer": spec["oneformer"]}},
                    exclusion_rows=extra)
                for temporary, target in files:
                    if target.exists():
                        raise FileExistsError(target)
                    temporary.replace(target)
                write(sample_dir / "policy.json", contract)
                region_policy.load_masks({"input_path": str(input_path),
                    "input_sha256": digest(input_path), "region_run_id": "evaluation-v2",
                    "region_policy": {**contract, "run_id": "evaluation-v2"}})
            original, _, _ = region_policy.constrain(semantic, rows, labels)
            for role in ("real_terrain/tree", "real_terrain/water"):
                if not np.array_equal(masks.get(role), original.get(role)):
                    raise ValueError("tree/waterの画素が変わっています")
            groups = mapping["datasets"][dataset]["groups"]
            totals[dataset, split].append(measure(
                truth, predictions(masks), groups, max_id=12 if dataset == "cmp" else 150))
            diagnostics[dataset, split].update({"wall_subtracted_pixels": metrics[
                "wall_subtracted_pixels"], "images": 1})
            if dataset == "cmp":
                removed = reasons["wall_parts"]
                wall = masks[visible_wall.WALL]
                diagnostics[dataset, split].update({
                    "removed_gt_wall": int((removed & (truth == 2)).sum()),
                    "removed_nonwall": int((removed & (truth != 2) & (truth != 0)).sum()),
                    "remaining_part_fp": int((wall & np.isin(truth, range(3, 13))).sum()),
                    "missing_wall_images": int(not wall.any())})
                if split == "holdout":
                    lab = rgb_to_oklab(rgb.astype(np.float64) / 255)
                    means = {}
                    for name, mask in (("prediction", wall), ("tp", wall & (truth == 2)),
                                       ("gt", truth == 2)):
                        count = int(mask.sum())
                        total = lab[mask].sum(axis=0)
                        pooled[name]["pixels"] += count
                        pooled[name]["sum"] += total
                        means[name] = total / count if count else None
                    for name in ("tp", "gt"):
                        if means["prediction"] is not None and means[name] is not None:
                            colors[name].append(float(np.linalg.norm(means["prediction"]
                                                                    - means[name])))
                    records.append({"file": row["file"], "means": {
                        name: value.tolist() if value is not None else None
                        for name, value in means.items()}})
            if (index + 1) % 100 == 0:
                print({"images": index + 1, "seconds": time.monotonic() - started}, flush=True)
        auxiliary_runtime = {"seconds": time.monotonic() - started, **peaks,
                             "torch_version": str(torch.__version__),
                             "candidate_images": 606}
        segment_models._unload()
        for row in (r for r in spec["inputs"] if r["file"] in spec["smoke"]):
            with np.load(args.inputs / row["file"], allow_pickle=False) as sample:
                rgb, truth = sample["rgb"], sample["truth"]
            payload = {"method": visible_wall.METHOD, "prompts": spec["production_prompts"],
                       "model_paths": {name: str(args.models / name)
                                       for name in ("dino", "sam2", "oneformer")}}
            parameters = {"models": {**models, "oneformer": spec["oneformer"]},
                          "threshold": 0.35, "text_threshold": 0.25}
            semantic, rows, runtime = segment_models.predict_regions(
                Image.fromarray(rgb), payload, parameters)
            extra = [r for r in rows if r[0] in visible_wall.EXTRA_PROMPTS]
            regular = [r for r in rows if r[0] not in visible_wall.EXTRA_PROMPTS]
            masks, _, metrics = visible_wall.constrain(
                semantic, regular, list(payload["prompts"]), extra)
            smoke.append({"dataset": row["dataset"], "runtime": runtime, "metrics": metrics,
                          "evaluation": measure(truth, predictions(masks), mapping["datasets"][
                              row["dataset"]]["groups"], max_id=12 if row["dataset"] == "cmp"
                              else 150)})
    except torch.cuda.OutOfMemoryError as error:
        (args.output / "stop").touch()
        raise NonRetryableError(region_policy.OOM_REASON) from error
    except NonRetryableError:
        (args.output / "stop").touch()
        raise
    finally:
        segment_models._unload()
    reports = {"/".join(key): aggregate(value) for key, value in totals.items()}
    write(args.output / "colors-private.json", records)
    write(args.output / "summary.json", {
        "version": VERSION, "freeze_sha256": digest(args.freeze),
        "policy_hash": spec["policy_hash"], "reports": reports,
        "decisions": {d: part_decision(reports[d + "/holdout"]["groups"]) for d in ("cmp", "ade")},
        "diagnostics": {"/".join(k): dict(v) for k, v in diagnostics.items()},
        "color": {"image_delta_ok": {name: distribution(colors[name]) for name in ("tp", "gt")},
                  "pooled": {name: {"pixels": value["pixels"], "mean_oklab": (value["sum"]
                             / value["pixels"]).tolist() if value["pixels"] else None}
                             for name, value in pooled.items()}},
        "tree_water_pixel_changes": 0, "gpu": torch.cuda.get_device_name(),
        "auxiliary_runtime": auxiliary_runtime, "smoke": smoke,
        "seconds": time.monotonic() - started, "quality_eligible": False,
        "independent_blind_confirmation": False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "run"))
    parser.add_argument("--output", type=Path, required=True)
    for name in ("data", "cache", "semantic", "previous", "freeze", "inputs", "models", "slot"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    if args.action == "freeze":
        freeze(args)
    else:
        run(args)


if __name__ == "__main__":
    main()
