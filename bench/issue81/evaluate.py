"""#81: 固定キャッシュの意味対応・無視画素・屋外選別を診断する（再推論なし）。"""

import argparse
import hashlib
import io
import time
import zipfile
from collections import Counter
from pathlib import Path

import numpy as np
import yaml
from bench.issue73.evaluate import digest, read, truth_for, write
from PIL import Image

from colorstats.segmentation_evaluation import pixel_counts, scores, select_ade
from colorstats.segmentation_quality import group_support, label_support


def text_digest(path):
    """Gitのテキストと同じLFで証跡を照合する。画像・マスクには使わない。"""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    plan_path = Path("bench/issue73/plan.json")
    plan = read(plan_path)
    baseline = read(Path("bench/issue73/baseline.json"))
    if baseline["plan_sha256"] != text_digest(plan_path):
        raise ValueError("#73の固定分割と基準が不一致です")
    old = yaml.safe_load(Path("bench/issue41/label-map.yaml").read_text(encoding="utf-8"))
    mapping_path = Path("bench/issue81/label-map.yaml")
    mapping = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
    # #73の旧対応表hashはCRLFのバイト列で固定されている。
    old_bytes = Path("bench/issue41/label-map.yaml").read_text(encoding="utf-8").encode()
    if hashlib.sha256(old_bytes.replace(b"\n", b"\r\n")).hexdigest() != plan["mapping_sha256"]:
        raise ValueError("#41の対応表が不一致です")
    archives = {}
    try:
        for name, sha in plan["archives"].items():
            if digest(args.data / name) != sha:
                raise ValueError("固定ZIPが不一致です")
            archives[name] = zipfile.ZipFile(args.data / name)
        counts = {
            mode: {split: {d: {g: Counter(tp=0, fp=0, fn=0)
                               for g in definition["datasets"][d]["groups"]}
                           for d in ("cmp", "ade")} for split in ("tune", "holdout")}
            for mode, definition in (("before", old), ("after", mapping))
        }
        confusion = {split: {} for split in ("tune", "holdout")}
        coverage = {split: {d: Counter() for d in ("cmp", "ade")}
                    for split in ("tune", "holdout")}
        for row in plan["rows"]:
            dataset, split = row["dataset"], row["split"]
            path = args.cache / dataset / Path(row["image"]).stem / "result.json"
            if digest(path) != row["record_sha256"]:
                raise ValueError("固定レコードが不一致です")
            record = read(path)
            if record["settings"] != plan["source_settings"][dataset]:
                raise ValueError("キャッシュのモデル設定が不一致です")
            annotation = archives[row["archive"]].read(row["annotation"])
            image = archives[row["archive"]].read(row["image"])
            if (hashlib.sha256(annotation).hexdigest() != row["truth_sha256"]
                    or hashlib.sha256(image).hexdigest() != row["sha256"]):
                raise ValueError("固定画像・正解が不一致です")
            truth = truth_for(row, archives)
            predictions = []
            for region in row["regions"]:
                mask_path = path.parent / region["mask"]
                if digest(mask_path) != region["sha256"]:
                    raise ValueError("固定マスクが不一致です")
                if region["confidence"] > plan["baseline_threshold"]:
                    predictions.append((region["label"], np.asarray(Image.open(mask_path)) > 0))
            for mode, definition in (("before", old), ("after", mapping)):
                values = pixel_counts(
                    truth, predictions, definition["datasets"][dataset]["groups"],
                    valid_ids=mapping["datasets"][dataset]["valid_ids"],
                )
                if mode == "before" and values != record["counts"]:
                    raise ValueError("#41の画像別画素数と不一致です")
                for group, value in values.items():
                    counts[mode][split][dataset][group].update(value)
            valid = np.isin(truth, mapping["datasets"][dataset]["valid_ids"])
            coverage[split][dataset].update(
                images=1, total_pixels=truth.size, valid_pixels=int(valid.sum()),
                ignored_pixels=int((~valid).sum()),
            )
            if dataset == "ade":
                masks = {}
                for label, mask in predictions:
                    masks.setdefault(label, np.zeros(truth.shape, dtype=bool))
                    masks[label] |= mask
                for group, value in old["datasets"]["ade"]["groups"].items():
                    masks["group/" + group] = np.logical_or.reduce(
                        [masks.get(label, np.zeros(truth.shape, dtype=bool))
                         for label in value["labels"]]
                    )
                for label, mask in masks.items():
                    histogram = np.bincount(truth[mask], minlength=151)
                    target = confusion[split].setdefault(label, np.zeros(151, dtype=np.int64))
                    target += histogram
        reports = {
            mode: {split: {d: {g: scores(v) for g, v in values.items()}
                           for d, values in datasets.items()} for split, datasets in splits.items()}
            for mode, splits in counts.items()
        }
        for split in ("tune", "holdout"):
            if reports["before"][split] != baseline[split]["labels"]:
                raise ValueError("#73の固定基準値と不一致です")
        manifest = read(args.cache / "ade/dataset-manifest.json")
        selected = []
        archive = archives["ADEChallengeData2016.zip"]
        for name in sorted(n for n in archive.namelist()
                           if "/images/validation/" in n and n.endswith(".jpg")):
            annotation = name.replace("/images/", "/annotations/").replace(".jpg", ".png")
            truth = np.asarray(Image.open(io.BytesIO(archive.read(annotation))))
            if select_ade(truth, mapping["ade_selection"]):
                selected.append(name)
        if selected != manifest["selected"] or set(selected) != {
            r["image"] for r in plan["rows"] if r["dataset"] == "ade"
        }:
            raise ValueError("原寸のADE屋外選別が不一致です")
        parts = yaml.safe_load(Path("taxonomy/parts.yaml").read_text(encoding="utf-8"))["groups"]
        terrain = yaml.safe_load(
            Path("taxonomy/terrain.yaml").read_text(encoding="utf-8")
        )["labels"]
        labels = {label for members in parts.values() for label in members} | set(terrain)
        support = label_support(reports["after"]["holdout"], mapping, labels)
        roles = group_support(reports["after"]["holdout"], mapping, mapping["roles"])
        confusion = {split: {label: values.tolist() for label, values in rows.items()}
                     for split, rows in confusion.items()}
        write(args.output / "confusion.json", {
            "class_names": {"0": "void", **manifest["class_names"]},
            "counts": confusion,
            "unit": "予測ラベル内でマスク和集合後の画素数。異ラベル間の重複は残す。",
        })
        decision = {
            "plan_sha256": text_digest(plan_path),
            "baseline_sha256": text_digest(Path("bench/issue73/baseline.json")),
            "definition_sha256": text_digest(Path("bench/issue81/definition.md")),
            "mapping_sha256": text_digest(mapping_path),
            "code_sha256": {name: text_digest(Path(name)) for name in (
                "bench/issue81/evaluate.py", "src/colorstats/segmentation_quality.py",
                "src/colorstats/segmentation_evaluation.py",
            )},
            "confusion_sha256": digest(args.output / "confusion.json"),
            "threshold": 0.50, "inference": False, "reports": reports,
            "coverage": coverage, "ade_selection": {"validation": 2000, "selected": len(selected),
                                                   "exact_manifest_match": True},
            "label_support": support, "group_support": roles,
            "supported_labels": [k for k, v in support.items() if v["supported"]],
            "supported_groups": [k for k, v in roles.items() if v["supported"]],
            "domains": {
                domain: {
                    "supported": sorted(k for k in members if support[k]["supported"]),
                    **{status: sorted(k for k in members if support[k]["status"] == status)
                       for status in ("group_only", "below_gate", "unmapped")},
                } for domain, members in (
                    ("real_building", {label for values in parts.values() for label in values}),
                    ("real_terrain", set(terrain)),
                )
            },
            "seconds": round(time.monotonic() - started, 3),
        }
        write(args.output / "decision.json", decision)
        print("images", len(plan["rows"]), "ADE selection", len(selected),
              "supported", decision["supported_labels"], "groups", decision["supported_groups"],
              "seconds", decision["seconds"], flush=True)
    finally:
        for archive in archives.values():
            archive.close()


if __name__ == "__main__":
    main()
