"""#73: 公開評価キャッシュを検証し、固定分割・基準・調整・採否を順に保存する。"""

import argparse
import hashlib
import io
import json
import subprocess
import time
import zipfile
from collections import Counter
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

from colorstats.analyze.segment_models import predict
from colorstats.segmentation_evaluation import pixel_counts, scores
from colorstats.segmentation_quality import GATES, adoption, indicators, label_support, split_groups


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def truth_for(row, archives):
    return np.asarray(Image.open(io.BytesIO(
        archives[row["archive"]].read(row["annotation"])
    )).resize(tuple(row["size"]), Image.Resampling.NEAREST))


def evaluate(rows, args, mapping, threshold, archives):
    counts = {d: {g: {"tp": 0, "fp": 0, "fn": 0}
                  for g in mapping["datasets"][d]["groups"]} for d in ("cmp", "ade")}
    coverage = {d: {"images": 0, "valid_pixels": 0, "total_pixels": 0} for d in counts}
    for row in rows:
        record_path = args.cache / row["dataset"] / Path(row["image"]).stem / "result.json"
        if digest(record_path) != row["record_sha256"]:
            raise ValueError("固定した予測レコードが変更されています")
        record = read(record_path)
        predictions = []
        for region in row["regions"]:
            path = record_path.parent / region["mask"]
            if digest(path) != region["sha256"]:
                raise ValueError("固定した予測マスクが変更されています")
            if region["confidence"] > threshold:
                mask = np.asarray(Image.open(path)) > 0
                predictions.append((region["label"], mask))
        groups = mapping["datasets"][row["dataset"]]["groups"]
        truth = truth_for(row, archives)
        values = pixel_counts(truth, predictions, groups)
        if threshold == 0.35 and values != record["counts"]:
            raise ValueError("既存画素数と再計算が一致しません")
        for label, value in values.items():
            for key, number in value.items():
                counts[row["dataset"]][label][key] += number
        summary = coverage[row["dataset"]]
        summary["images"] += 1
        summary["total_pixels"] += truth.size
        summary["valid_pixels"] += int(np.isin(
            truth, [i for g in groups.values() for i in g["ids"]]
        ).sum())
    if any(value["images"] == 0 for value in coverage.values()):
        raise ValueError("両データの画像が各集合に必要です")
    return {d: {g: scores(v) for g, v in values.items()}
            for d, values in counts.items()}, coverage


def freeze(args, mapping, archives):
    args.output.mkdir(parents=True, exist_ok=False)
    subjects = read(args.subjects)
    by_sha = {}
    for row in subjects["assets"]:
        if row["subject_id"]:
            by_sha.setdefault(row["sha256"], set()).add(row["subject_id"])
    rows = []
    source_settings = {}
    for dataset in ("cmp", "ade"):
        manifest = read(args.cache / dataset / "dataset-manifest.json")
        settings = read(args.cache / dataset / "settings.json")
        source_settings[dataset] = settings
        if settings["threshold"] != 0.35 or settings["text_threshold"] != 0.25:
            raise ValueError("既定設定のキャッシュが必要です")
        for source in manifest["archives"]:
            if digest(args.data / source["filename"]) != source["sha256"]:
                raise ValueError("公開ZIPのhashが既存manifestと一致しません")
        for name in manifest["selected"]:
            archive = next(a for a in manifest["archives"]
                           if name in archives[a["filename"]].namelist())["filename"]
            annotation = (name.replace("/images/", "/annotations/").replace(".jpg", ".png")
                          if dataset == "ade" else str(Path(name).with_suffix(".png")))
            raw = archives[archive].read(name)
            sha = hashlib.sha256(raw).hexdigest()
            candidates = by_sha.get(sha, set())
            if len(candidates) > 1:
                raise ValueError("同一SHAに複数の確定subjectがあります")
            image = Image.open(io.BytesIO(raw)).convert("RGB")
            image.thumbnail((512, 512), Image.Resampling.LANCZOS)
            record_path = args.cache / dataset / Path(name).stem / "result.json"
            record = read(record_path)
            if record["settings"] != settings or record["image"] != name:
                raise ValueError("予測設定または画像名が不一致です")
            if tuple(record["evaluation_size"]) != image.size:
                raise ValueError("評価サイズが不一致です")
            regions = [{**r, "sha256": digest(record_path.parent / r["mask"])}
                       for r in record["regions"]]
            rows.append({
                "id": f"{dataset}/{name}", "dataset": dataset, "image": name,
                "archive": archive, "annotation": annotation, "sha256": sha,
                "truth_sha256": hashlib.sha256(archives[archive].read(annotation)).hexdigest(),
                "resized_rgb_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
                "subject_id": next(iter(candidates), None), "size": image.size,
                "record_sha256": digest(record_path), "regions": regions,
            })
    assignments = split_groups(rows)
    for row in rows:
        row.update(assignments[row["id"]])
    plan = {
        "seed": 73, "base_commit": "69ebe7cdb81bcf5c5d6d6efed377be4c63b19359",
        "created_before_tuning": True, "gates": GATES,
        "candidates": [0.45, 0.55], "baseline_threshold": 0.35,
        "mapping_sha256": digest(args.mapping), "subject_snapshot_sha256": digest(args.subjects),
        "subject_run_id": subjects["run_id"], "source_settings": source_settings,
        "archives": {name: digest(args.data / name) for name in archives},
        "code_sha256": {str(p): digest(p) for p in (
            Path("bench/issue73/evaluate.py"), Path("src/colorstats/segmentation_quality.py"),
            Path("src/colorstats/segmentation_evaluation.py"),
            Path("src/colorstats/analyze/segment_models.py"),
        )},
        "rows": rows,
        "split_counts": dict(Counter(f'{r["dataset"]}/{r["split"]}' for r in rows)),
        "known_subject_images": sum(r["subject_id"] is not None for r in rows),
        "limitation": ("公開データに対象同定表なし。SHAと既知subjectだけを群化。"
                       "未知対象の独立性・盲検は保証しない。"),
    }
    plan["leakage"] = {
        field: sum(len({r["split"] for r in rows if r[field] == value}) > 1
                   for value in {r[field] for r in rows if r[field] is not None})
        for field in ("sha256", "subject_id")
    }
    if any(plan["leakage"].values()):
        raise ValueError("集合間リークがあります")
    write(args.output / "plan.json", plan)
    baseline = {}
    for split in ("tune", "holdout"):
        labels, coverage = evaluate([r for r in rows if r["split"] == split],
                                    args, mapping, 0.35, archives)
        baseline[split] = {"labels": labels, "coverage": coverage}
    write(args.output / "baseline.json", {
        "plan_sha256": digest(args.output / "plan.json"), **baseline,
    })
    print("freeze", plan["split_counts"], "known_subject_images", plan["known_subject_images"])


def verify_plan(args):
    plan = read(args.output / "plan.json")
    if digest(args.mapping) != plan["mapping_sha256"] or plan["gates"] != GATES:
        raise ValueError("対応表または固定閾値が変更されています")
    for name, sha in plan["archives"].items():
        if digest(args.data / name) != sha:
            raise ValueError("固定ZIPが変更されています")
    for name, sha in plan["code_sha256"].items():
        if digest(Path(name)) != sha:
            raise ValueError("固定コードが変更されています")
    baseline = read(args.output / "baseline.json")
    if baseline["plan_sha256"] != digest(args.output / "plan.json"):
        raise ValueError("分割manifestが変更されています")
    return plan, baseline


def tune(args, mapping, archives):
    plan, baseline = verify_plan(args)
    rows = [r for r in plan["rows"] if r["split"] == "tune"]
    trials = {}
    for threshold in plan["candidates"]:
        labels, coverage = evaluate(rows, args, mapping, threshold, archives)
        trials[str(threshold)] = {"labels": labels, "coverage": coverage,
                                 "indicators": indicators(labels)}
    # holdoutを参照せず、細部IoU・適合率と壁適合率の和で候補を一つに固定する。
    selected = max(plan["candidates"], key=lambda t: sum(
        trials[str(t)]["indicators"][key] or 0
        for key in ("detail_iou", "detail_precision", "wall_precision")
    ))
    write(args.output / "tuning.json", {
        "plan_sha256": digest(args.output / "plan.json"),
        "baseline_sha256": digest(args.output / "baseline.json"),
        "selected_threshold": selected, "trials": trials,
    })
    print("tune selected", selected)


def gpu_check(args):
    plan, _ = verify_plan(args)
    selected = read(args.output / "tuning.json")["selected_threshold"]
    processes = subprocess.check_output([
        "nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"
    ], text=True).strip()
    if processes:
        raise RuntimeError("GPUが他の計算プロセスに使用されています")
    for component in ("sam2", "dino"):
        for name, sha in plan["source_settings"]["cmp"]["model_sha256"].items():
            if name.startswith(component + "/") and digest(args.models / name) != sha:
                raise ValueError("配置済みモデルがキャッシュのモデルと不一致です")
    checks = []
    for dataset in ("cmp", "ade"):
        row = next(r for r in plan["rows"] if r["dataset"] == dataset and r["split"] == "tune")
        with zipfile.ZipFile(args.data / row["archive"]) as archive:
            image = Image.open(io.BytesIO(archive.read(row["image"]))).convert("RGB")
        image.thumbnail((512, 512), Image.Resampling.LANCZOS)
        directory = args.cache / dataset / Path(row["image"]).stem
        for threshold in (0.35, selected):
            predictions, metrics = predict(
                image, "sam2-dino", {c: str(args.models / c) for c in ("sam2", "dino")},
                plan["source_settings"][dataset]["prompts"], threshold, 0.25,
            )
            expected = [r for r in row["regions"] if r["confidence"] > threshold]
            equal = len(expected) == len(predictions) and all(
                label == region["label"]
                and np.array_equal(mask, np.asarray(Image.open(directory / region["mask"])) > 0)
                for (label, mask, _), region in zip(predictions, expected, strict=True)
            )
            checks.append({"image": row["id"], "threshold": threshold,
                           "regions": len(predictions), "exact_masks": equal, "metrics": metrics})
            if not equal:
                raise ValueError("GPU再推論とキャッシュの閾値抽出が一致しません")
    write(args.output / "gpu-check.json", {
        "plan_sha256": digest(args.output / "plan.json"),
        "tuning_sha256": digest(args.output / "tuning.json"), "checks": checks,
    })
    print("GPU cache equivalence", len(checks), "checks passed")


def finish(args, mapping, archives):
    plan, baseline = verify_plan(args)
    tuning = read(args.output / "tuning.json")
    if tuning["plan_sha256"] != digest(args.output / "plan.json"):
        raise ValueError("調整時の分割が不一致です")
    if tuning["baseline_sha256"] != digest(args.output / "baseline.json"):
        raise ValueError("調整時の基準値が不一致です")
    gpu = read(args.output / "gpu-check.json")
    if (gpu["plan_sha256"] != digest(args.output / "plan.json")
            or gpu["tuning_sha256"] != digest(args.output / "tuning.json")
            or len(gpu["checks"]) != 4
            or not all(r["exact_masks"] for r in gpu["checks"])):
        raise ValueError("GPU照合未完了です")
    threshold = tuning["selected_threshold"]
    candidate, coverage = evaluate(
        [r for r in plan["rows"] if r["split"] == "holdout"], args, mapping, threshold, archives,
    )
    decision = adoption(baseline["holdout"]["labels"], candidate)
    adopted = candidate if decision["accepted"] else baseline["holdout"]["labels"]
    parts = yaml.safe_load(Path("taxonomy/parts.yaml").read_text(encoding="utf-8"))
    terrain = yaml.safe_load(Path("taxonomy/terrain.yaml").read_text(encoding="utf-8"))
    labels = {label for values in parts["groups"].values() for label in values}
    labels.update(terrain["labels"])
    support = label_support(adopted, mapping, labels)
    write(args.output / "decision.json", {
        "plan_sha256": digest(args.output / "plan.json"),
        "baseline_sha256": digest(args.output / "baseline.json"),
        "tuning_sha256": digest(args.output / "tuning.json"),
        "candidate_threshold": threshold, **decision,
        "adopted_threshold": threshold if decision["accepted"] else 0.35,
        "candidate": candidate, "coverage": coverage, "label_support": support,
        "supported": [label for label, row in support.items() if row["supported"]],
    })
    print("decision", decision, "supported", [k for k, v in support.items() if v["supported"]])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "tune", "gpu", "finish"))
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, default=Path("bench/issue41/label-map.yaml"))
    parser.add_argument("--subjects", type=Path)
    parser.add_argument("--models", type=Path)
    args = parser.parse_args()
    started = time.monotonic()
    mapping = yaml.safe_load(args.mapping.read_text(encoding="utf-8"))
    archives = {p.name: zipfile.ZipFile(p) for p in args.data.glob("*.zip")}
    try:
        {"freeze": freeze, "tune": tune, "gpu": lambda a, m, z: gpu_check(a),
         "finish": finish}[args.phase](args, mapping, archives)
    finally:
        for archive in archives.values():
            archive.close()
    print("seconds", round(time.monotonic() - started, 3), flush=True)


if __name__ == "__main__":
    main()
