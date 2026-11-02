"""公開ZIPから選定・sam2-dino推論・画素集計を行う（DB操作なし）。"""

import argparse
import hashlib
import io
import json
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

from colorstats.analyze.segment_models import predict
from colorstats.segmentation_evaluation import pixel_counts, scores, select_ade

PROMPTS = {
    "wall_main": "building wall", "wall_secondary": "secondary building wall",
    "gable_wall": "gable wall", "band_course": "horizontal stone band", "cornice": "cornice",
    "column": "column", "window_glass": "window glass", "window_frame": "window frame",
    "door": "door", "shutter": "window shutter", "relief": "carved relief",
    "accent_other": "architectural ornament", "stairs_entry": "entrance stairs",
    "railing": "railing", "fence": "fence", "path": "paved path", "path_natural": "dirt path",
    "ground_soil": "soil", "ground_grass": "grass", "rock_face": "rock cliff",
    "rock_scree": "loose rocks", "sand": "sand", "water": "water",
    "vegetation_tree_canopy": "tree canopy", "tree_trunk": "tree trunk",
}
SOURCES = {
    "CMP_facade_DB_base.zip": (
        "https://cmp.felk.cvut.cz/~tylecr1/facade/CMP_facade_DB_base.zip", "CC BY-SA"),
    "CMP_facade_DB_extended.zip": (
        "https://cmp.felk.cvut.cz/~tylecr1/facade/CMP_facade_DB_extended.zip", "CC BY-SA"),
    "ADEChallengeData2016.zip": (
        "https://data.csail.mit.edu/places/ADEchallenge/ADEChallengeData2016.zip",
        "画像: 非営利の研究・教育目的のみ、画像著作権はMITにない。アノテーション: BSD-3"),
}


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--dataset", choices=["cmp", "ade"], required=True)
    parser.add_argument("--select-only", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    mapping = yaml.safe_load(args.mapping.read_text(encoding="utf-8"))
    groups = mapping["datasets"][args.dataset]["groups"]
    labels = {label for group in groups.values() for label in group["labels"]}
    prompts = {label: PROMPTS[label] for label in sorted(labels)}
    manifest = {
        "archives": [], "selected": [],
        "selection": mapping["ade_selection"] if args.dataset == "ade"
        else {"split": "base+extended", "condition": "全606枚"},
    }
    samples = []
    archives = []
    for filename, (url, license_text) in SOURCES.items():
        if (args.dataset == "ade") != filename.startswith("ADE"):
            continue
        path = args.data / filename
        archive = zipfile.ZipFile(path)
        archives.append(archive)
        # CRC照合は画像・正解を実際に読むときにも行われる。
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        names = archive.namelist()
        images = sorted(n for n in names if n.lower().endswith(".jpg"))
        manifest["archives"].append({
            "filename": filename, "url": url, "sha256": digest, "bytes": path.stat().st_size,
            "retrieved_at_utc": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
            "license": license_text, "image_count": len(images),
            "annotation_count": sum(n.endswith(".png") for n in names),
        })
        if args.dataset == "cmp":
            assert len(images) == (378 if "base" in filename else 228), len(images)
            observed = {}
            for name in names:
                if name.endswith(".xml"):
                    root = ET.fromstring("<root>" + archive.read(name).decode() + "</root>")
                    for obj in root:
                        observed[int(obj.findtext("label"))] = obj.findtext("labelname").strip()
            for group in groups.values():
                assert [observed[i] for i in group["ids"]] == group["source"]
            manifest["observed_class_names"] = {1: "background", **observed}
            for name in images:
                samples.append((archive, name, str(Path(name).with_suffix(".png"))))
        else:
            info = next(n for n in names if n.endswith("objectInfo150.txt"))
            rows = archive.read(info).decode().splitlines()[1:]
            class_names = {int(row.split()[0]): row.split("\t")[-1] for row in rows if row.strip()}
            manifest["class_names"] = class_names
            mapped_ids = {i for group in groups.values() for i in group["ids"]}
            manifest["excluded_classes"] = {i: name for i, name in class_names.items()
                                             if i not in mapped_ids}
            manifest["excluded_classes"][0] = "unlabeled（void）"
            for group in groups.values():
                for index, name in zip(group["ids"], group["source"], strict=True):
                    assert name in class_names[index].split(", "), (index, name, class_names[index])
            validation = [n for n in images if "/images/validation/" in n]
            assert len(validation) == 2000, len(validation)
            manifest["validation_count"] = len(validation)
            for name in validation:
                annotation = name.replace("/images/", "/annotations/").replace(".jpg", ".png")
                truth = np.asarray(Image.open(io.BytesIO(archive.read(annotation))))
                if select_ade(truth, mapping["ade_selection"]):
                    samples.append((archive, name, annotation))
    manifest["selected"] = [name for _, name, _ in samples]
    manifest["selected_count"] = len(samples)
    manifest_path = args.output / "dataset-manifest.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if ([a["sha256"] for a in previous["archives"]]
                != [a["sha256"] for a in manifest["archives"]]
                or previous["selected"] != manifest["selected"]):
            raise ValueError("取得データまたは選定対象が変わっています。別のoutputが必要です")
    save(manifest_path, manifest)
    if args.select_only:
        for archive in archives:
            archive.close()
        return
    settings = {
        "method": "sam2-dino", "threshold": 0.35, "text_threshold": 0.25,
        "max_image_side": 512, "truth_resize": "nearest", "prompts": prompts,
        "mapping_sha256": hashlib.sha256(
            args.mapping.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
        "overlap": "同一グループは和集合。異なるグループの重複は誤ラベル側のFP。",
        "ignored": "未対応の正解IDの画素を全グループで無視。未対応予測ラベルも評価外。",
        "model_sha256": {},
    }
    for component in ("sam2", "dino"):
        for path in sorted((args.models / component).glob("*")):
            if path.is_file():
                with path.open("rb") as stream:
                    settings["model_sha256"][f"{component}/{path.name}"] = hashlib.file_digest(
                        stream, "sha256").hexdigest()
    save(args.output / "settings.json", settings)
    counts = {name: {"tp": 0, "fp": 0, "fn": 0} for name in groups}
    coverage = {"valid_pixels": 0, "total_pixels": 0, "zero_valid_images": [],
                "predicted_regions": 0}
    started = time.monotonic()
    for index, (archive, name, annotation) in enumerate(samples):
        key = Path(name).stem
        directory = args.output / key
        directory.mkdir(exist_ok=True)
        record_path = directory / "result.json"
        if record_path.exists():
            record = json.loads(record_path.read_text(encoding="utf-8"))
            if record["settings"] != settings:
                raise ValueError("既存結果の設定が異なります。別のoutputを指定してください")
        else:
            processes = subprocess.check_output([
                "nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader",
            ], text=True).strip()
            # 自分のCUDAコンテキスト以外の計算プロセスがあれば開始しない。
            import os
            if set(processes.splitlines()) - {str(os.getpid())}:
                raise RuntimeError("GPUが他の計算プロセスに使用されています")
            image = Image.open(io.BytesIO(archive.read(name))).convert("RGB")
            original_size = image.size
            image.thumbnail((512, 512), Image.Resampling.LANCZOS)
            truth = np.asarray(Image.open(io.BytesIO(archive.read(annotation))).resize(
                image.size, Image.Resampling.NEAREST))
            predictions, metrics = predict(
                image, "sam2-dino", {c: str(args.models / c) for c in ("sam2", "dino")},
                prompts, 0.35, 0.25,
            )
            regions = []
            for region_index, (label, mask, confidence) in enumerate(predictions):
                mask_name = f"{region_index:04d}.png"
                Image.fromarray(mask.astype(np.uint8) * 255).save(directory / mask_name)
                regions.append({"label": label, "mask": mask_name, "confidence": confidence})
            record = {
                "image": name, "settings": settings, "original_size": original_size,
                "evaluation_size": image.size, "metrics": metrics, "regions": regions,
                "counts": pixel_counts(truth, [(label, mask) for label, mask, _ in predictions],
                                       groups),
                "valid_pixels": int(np.isin(truth, [i for g in groups.values()
                                                     for i in g["ids"]]).sum()),
                "total_pixels": truth.size,
            }
            save(record_path, record)
        for label, values in record["counts"].items():
            for count_key, value in values.items():
                counts[label][count_key] += value
        coverage["valid_pixels"] += record["valid_pixels"]
        coverage["total_pixels"] += record["total_pixels"]
        coverage["predicted_regions"] += len(record["regions"])
        if record["valid_pixels"] == 0:
            coverage["zero_valid_images"].append(name)
        report = {
            "dataset": args.dataset, "completed": index + 1, "selected": len(samples),
            "complete": index + 1 == len(samples), "settings": settings,
            "labels": {label: scores(values) for label, values in counts.items()},
            "coverage": coverage,
        }
        save(args.output / "report.json", report)
        print(args.dataset, index + 1, "/", len(samples), key,
              round(time.monotonic() - started, 1), "seconds", flush=True)
    for archive in archives:
        archive.close()


if __name__ == "__main__":
    main()
