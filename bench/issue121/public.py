"""公開正解の固定・旧指標再現・同一入力での3方式比較（DB/API接続なし）。"""

import argparse
import hashlib
import io
import json
import time
import zipfile
from collections import defaultdict
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import yaml
from bench.issue73.evaluate import digest, read, truth_for, write
from bench.issue81.evaluate import text_digest
from bench.issue121.quality import aggregate, measure, part_decision
from PIL import Image

from colorstats.analyze import region_policy, segment_models
from colorstats.segmentation_evaluation import pixel_counts, scores

FILES = ["bench/issue121/plan.md", "bench/issue121/public.py", "bench/issue121/quality.py",
         "bench/issue121/owned.py", "bench/issue121/inventory.py",
         "bench/issue73/plan.json", "bench/issue81/label-map.yaml",
         "configs/segment_stats.yaml", "src/colorstats/analyze/segment_models.py",
         "src/colorstats/analyze/region_policy.py", "src/colorstats/analyze/region-parents-v2.json",
         "src/colorstats/segmentation_evaluation.py"]
METHODS = ("raw", "prompt_post", "oneformer")


def freeze(data, models, output):
    """入力ZIP・旧分割・実重み・評価仕様を、新予測に先立ち追記不能な新規ファイルへ固定する。"""
    plan = read(Path("bench/issue73/plan.json"))
    if len(plan["rows"]) != 1223:
        raise ValueError("旧固定集合の件数が不一致です")
    for name, expected in plan["archives"].items():
        if digest(data / name) != expected:
            raise ValueError("公開ZIPのSHAが旧固定版と不一致です")
    identities = {split: {row["sha256"] for row in plan["rows"] if row["split"] == split}
                  for split in ("tune", "holdout")}
    if identities["tune"] & identities["holdout"]:
        raise ValueError("調整/確認間のSHA重複があります")
    actual = {}
    for name in ("dino", "sam2"):
        expected_files = {key.split("/", 1)[1]: value for key, value in
                          plan["source_settings"]["cmp"]["model_sha256"].items()
                          if key.startswith(name + "/")}
        actual[name] = {filename: digest(models / name / filename) for filename in expected_files}
        for settings in plan["source_settings"].values():
            if any(settings["model_sha256"][name + "/" + filename] != value
                   for filename, value in actual[name].items()):
                raise ValueError("旧キャッシュと推論モデルのSHAが不一致です")
    spec = {"version": "issue121-v1", "base_commit": "d3c742c", "seed": 12120261107,
            "frozen_at": datetime.now(UTC).isoformat(),
            "files": {name: text_digest(Path(name)) for name in FILES},
            "archives": plan["archives"], "models": actual,
            "oneformer": region_policy.model_configuration(models / "oneformer"),
            "policy_hash": region_policy.policy_hash(),
            "parent_table": region_policy.parent_table_reference(),
            "transform": region_policy.TRANSFORM, "methods": list(METHODS),
            "thresholds": {"raw": 0.35, "prompt_post": 0.45, "oneformer": 0.35},
            "gates": {"precision": 0.80, "recall": 0.30},
            "split_sha_overlap": 0, "paired_images": len(plan["rows"]),
            "ade_validation_images": 2000, "before_new_predictions": True,
            "known_regression_set": True, "quality_eligible": False}
    write(output, spec)
    return spec


def cached_predictions(row, cache):
    """旧推論レコードと候補maskをSHA照合し、未閾値処理の候補を返す。"""
    path = cache / row["dataset"] / Path(row["image"]).stem / "result.json"
    if digest(path) != row["record_sha256"]:
        raise ValueError("旧推論レコードのSHAが不一致です")
    record = read(path)
    rows = []
    for region in row["regions"]:
        mask = path.parent / region["mask"]
        if digest(mask) != region["sha256"]:
            raise ValueError("旧maskのSHAが不一致です")
        rows.append((region["label"], np.asarray(Image.open(mask)) > 0, region["confidence"]))
    return rows, record


def postprocess(rows, groups):
    """既選定0.45超の同群をunionし、群間の競合をvoidにする比較基準。"""
    if not rows:
        return []
    merged = {key: np.zeros(rows[0][1].shape, dtype=bool) for key in groups}
    for label, mask, confidence in rows:
        if confidence > 0.45:
            for key, group in groups.items():
                if label in group["labels"]:
                    merged[key] |= mask
    conflict = np.sum(list(merged.values()), axis=0) > 1
    return [(groups[key]["labels"][0], mask & ~conflict) for key, mask in merged.items()]


def verify_spec(spec):
    for name, expected in spec["files"].items():
        if text_digest(Path(name)) != expected:
            raise ValueError("予測前の固定後に評価仕様・コードが変更されています")
    if spec["policy_hash"] != region_policy.policy_hash():
        raise ValueError("固定policyが不一致です")


def run(args):
    spec = read(args.freeze)
    verify_spec(spec)
    plan = read(Path("bench/issue73/plan.json"))
    mapping = yaml.safe_load(Path("bench/issue81/label-map.yaml").read_text("utf-8"))
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    totals, conditional = defaultdict(list), defaultdict(lambda: defaultdict(list))
    model = processor = None
    metrics = {"inference": not args.cached_only, "seconds": 0, "images": 0}
    if not args.cached_only:
        import torch
        from transformers import OneFormerForUniversalSegmentation
        from transformers.models.oneformer.modeling_oneformer import OneFormerSinePositionEmbedding

        if region_policy.model_configuration(args.models / "oneformer") != spec["oneformer"]:
            raise ValueError("固定OneFormerモデルが不一致です")
        segment_models._unload()
        torch.cuda.reset_peak_memory_stats()
        processor = segment_models._oneformer_processor(args.models / "oneformer")
        processor.image_processor.size = {key: spec["transform"][key]
                                          for key in ("shortest_edge", "longest_edge")}
        processor.image_processor._max_size = spec["transform"]["longest_edge"]
        model = OneFormerForUniversalSegmentation.from_pretrained(
            args.models / "oneformer", local_files_only=True, weights_only=True).eval().to("cuda")
        segment_models._uncache_positions(model, OneFormerSinePositionEmbedding)
        region_policy.validate_labels({str(k): v for k, v in model.config.id2label.items()})
        from importlib.metadata import version
        metrics["versions"] = {name: version(name) for name in ("torch", "transformers", "Pillow")}
        if (metrics["versions"]["torch"].split("+")[0] != "2.11.0"
                or metrics["versions"]["transformers"] != "4.57.6"):
            raise ValueError("固定したGPU実行版が不一致です")
    try:
        with ExitStack() as stack:
            archives = {}
            for name, expected in spec["archives"].items():
                if digest(args.data / name) != expected:
                    raise ValueError("入力ZIPのSHAが不一致です")
                archives[name] = stack.enter_context(zipfile.ZipFile(args.data / name))
            rows = [row for row in plan["rows"] if args.dataset in ("all", row["dataset"])]
            for index, row in enumerate(rows):
                dataset, split = row["dataset"], row["split"]
                groups = mapping["datasets"][dataset]["groups"]
                truth = truth_for(row, archives)
                raw_image = archives[row["archive"]].read(row["image"])
                annotation = archives[row["archive"]].read(row["annotation"])
                if (hashlib.sha256(raw_image).hexdigest() != row["sha256"]
                        or hashlib.sha256(annotation).hexdigest() != row["truth_sha256"]):
                    raise ValueError("入力画像・正解のSHAが不一致です")
                candidates, record = cached_predictions(row, args.cache)
                if record["settings"] != plan["source_settings"][dataset]:
                    raise ValueError("旧キャッシュ設定が不一致です")
                raw = [(label, mask) for label, mask, confidence in candidates if confidence > 0.35]
                counts = pixel_counts(truth, raw, groups,
                                      valid_ids=mapping["datasets"][dataset]["valid_ids"])
                for key, value in counts.items():
                    conditional[dataset, split][key].append(value)
                predictions = {"raw": raw, "prompt_post": postprocess(candidates, groups)}
                if model is not None:
                    image = Image.open(io.BytesIO(raw_image)).convert("RGB")
                    image.thumbnail((512, 512), Image.Resampling.LANCZOS)
                    rgb_hash = hashlib.sha256(image.tobytes()).hexdigest()
                    if list(image.size) != row["size"] or rgb_hash != row["resized_rgb_sha256"]:
                        raise ValueError("固定RGBと座標が不一致です")
                    torch.manual_seed(0)
                    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
                        inputs = processor(images=image, task_inputs=["semantic"],
                                           return_tensors="pt").to("cuda")
                        outputs = model(**inputs)
                        semantic = processor.post_process_semantic_segmentation(
                            outputs, target_sizes=[(image.height, image.width)],
                        )[0].cpu().numpy().astype(np.uint8)
                    del inputs, outputs
                    sample = args.output / f"semantic-{index:04d}.png"
                    Image.fromarray(semantic).save(sample)
                    effective, _, _ = region_policy.constrain(semantic, [
                        item for item in candidates if item[2] > 0.35],
                        {label for label, _, _ in candidates})
                    predictions["oneformer"] = [
                        ("wall_main" if role == "real_building/wall" else
                         "vegetation_tree_canopy" if role == "real_terrain/tree" else
                         role.split("/", 1)[1], mask) for role, mask in effective.items()]
                for method, prediction in predictions.items():
                    totals[method, dataset, split].append(measure(
                        truth, prediction, groups, max_id=12 if dataset == "cmp" else 150))
                if (index + 1) % 50 == 0:
                    print(json.dumps({"images": index + 1, "seconds": time.monotonic() - started}),
                          flush=True)
            metrics["images"] = len(rows)
            if model is not None:
                torch.cuda.synchronize()
                metrics.update(gpu=torch.cuda.get_device_name(),
                               peak_allocated_bytes=torch.cuda.max_memory_allocated(),
                               peak_reserved_bytes=torch.cuda.max_memory_reserved())
    finally:
        del model, processor
        segment_models._unload() if not args.cached_only else None
    old = read(Path("bench/issue81/decision.json"))["reports"]["after"]
    reproduction = {}
    for (dataset, split), groups in conditional.items():
        values = {name: scores({key: sum(row[key] for row in rows)
                               for key in ("tp", "fp", "fn")}) for name, rows in groups.items()}
        if values != old[split][dataset]:
            raise ValueError("旧#81条件付き指標の再現が不一致です")
        reproduction[f"{dataset}/{split}"] = values
    reports = {"/".join(key): aggregate(values) for key, values in totals.items()}
    gates = {key: part_decision(value["groups"]) for key, value in reports.items()
             if key.endswith("/holdout")}
    metrics["seconds"] = time.monotonic() - started
    write(args.output / "summary.json", {"freeze_sha256": digest(args.freeze),
          "old81_reproduced": True, "conditional": reproduction, "reports": reports,
          "decisions": gates, "runtime": metrics, "quality_eligible": False,
          "unverified": ["所有画像目視", "ADE全validation", "色に残る汚染",
                         "対応外部位", "人物・内容ゲート"]})
    print(json.dumps({"old81_reproduced": True, **metrics}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["freeze", "run"])
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--dataset", choices=["all", "cmp", "ade"], default="all")
    parser.add_argument("--cached-only", action="store_true")
    args = parser.parse_args()
    if args.action == "freeze":
        freeze(args.data, args.models, args.output)
    else:
        if not args.freeze or not args.cache:
            parser.error("runには--freezeと--cacheが必要です")
        run(args)


if __name__ == "__main__":
    main()
