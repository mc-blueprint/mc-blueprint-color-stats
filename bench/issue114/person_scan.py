"""既存segmentを保全し、ローカル重みで人物の補助検出を行う。DBは読取り専用。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID

import numpy as np
import yaml
from PIL import Image, ImageFilter
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from colorstats.analyze.segment_models import predict
from colorstats.schema.models import ProcessingRun, Region

VERSION = "person-sam2-dino-v2"
PROMPTS = {"person": "person"}
BATCH = Path("/mnt/data/derived/issue114-batch1-20261106")
ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def subject_coverage(regions, shape, building, terrain):
    masks = {name: np.zeros(shape, dtype=bool) for name in ("building", "terrain")}
    for label, path in regions:
        name = "building" if label in building else "terrain" if label in terrain else None
        if name:
            with Image.open(path) as image:
                mask = np.asarray(image.convert("L")) != 0
            if mask.shape != shape:
                raise ValueError("主体maskの寸法が入力と一致しません")
            masks[name] |= mask
    return {name: float(mask.mean()) for name, mask in masks.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("ubuntu1", "ubuntu2"), required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    target = args.root / args.host
    target.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((BATCH / args.host / "manifest.json").read_text())
    report = json.loads((BATCH / args.host / "report.json").read_text())
    runs = {row["asset_id"]: UUID(row["run_id"]) for row in report["jobs"]
            if row["stage"] == "segment" and row["status"] == "succeeded"}
    if args.host == "ubuntu1":
        db = create_engine(os.environ["DATABASE_URL"], hide_parameters=True)
    else:
        from bench.issue105.production import engine

        db = engine(False)
    try:
        with Session(db) as session:
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            models = session.get(ProcessingRun, next(iter(runs.values()))).parameters["models"]
            regions = {}
            for row in session.scalars(select(Region).where(
                Region.processing_run_id.in_(list(runs.values())),
            )):
                regions.setdefault(str(row.asset_id), []).append((row.label, row.mask_path))
    finally:
        db.dispose()
    model_root = (Path("/opt/colorstats/work/issue66-20261104/models")
                  if args.host == "ubuntu1" else Path("/mnt/data/work/issue-40/models"))
    paths = {name: str(model_root / name) for name in models}
    for name, data in models.items():
        for filename, expected in data["files"].items():
            if digest(model_root / name / filename) != expected:
                raise ValueError("既存segmentのモデルhashと一致しません")
    parts = yaml.safe_load((ROOT / "taxonomy/parts.yaml").read_text())
    terrain = set(yaml.safe_load((ROOT / "taxonomy/terrain.yaml").read_text())["labels"])
    building = {label for group, labels in parts["groups"].items() if group != "context"
                for label in labels}
    policy = {"version": VERSION, "prompts": PROMPTS, "threshold": 0.35,
              "text_threshold": 0.25, "mask_padding_pixels": 2, "models": models,
              "scanner_sha256": digest(__file__), "input_manifest_sha256": digest(
                  BATCH / args.host / "manifest.json")}
    (target / "scan-manifest.json").write_text(json.dumps(policy, indent=2) + "\n")
    for index, row in enumerate(manifest["assets"]):
        aid = row["asset_id"]
        if digest(row["input_path"]) != row["input_sha256"]:
            raise ValueError("固定prep画像のhashが変わっています")
        with Image.open(row["input_path"]) as source:
            image = source.convert("RGB")
        detected, metrics = predict(image, "sam2-dino", paths, models, PROMPTS, 0.35, 0.25)
        union = np.zeros((image.height, image.width), dtype=bool)
        records = []
        for label, mask, confidence in detected:
            if not mask.any():
                continue
            union |= mask
            y, x = np.nonzero(mask)
            records.append({"label": label, "confidence": confidence,
                            "area_ratio": float(mask.mean()),
                            "bbox": [int(x.min()), int(y.min()), int(x.max())+1, int(y.max())+1]})
        person = Image.fromarray(union.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(5))
        mask_path = target / f"{aid}.png"
        person.save(mask_path)
        data = {"asset_id": aid, "version": VERSION, "input_path": row["input_path"],
                "input_sha256": row["input_sha256"], "region_run_id": str(runs[aid]),
                "person_ratio": float(union.mean()), "mask_ratio": float(
                    (np.asarray(person) != 0).mean()), "detections": records,
                "subject_coverage": subject_coverage(regions.get(aid, []), union.shape,
                                                     building, terrain),
                "mask_path": str(mask_path), "mask_sha256": digest(mask_path),
                "metrics": metrics}
        with (target / f"{aid}.json").open("x") as stream:
            json.dump(data, stream, indent=2)
        if (index + 1) % 50 == 0:
            print(json.dumps({"host": args.host, "scanned": index + 1}), flush=True)
    (target / "done").touch()
    print(json.dumps({"host": args.host, "scanned": len(manifest["assets"])}), flush=True)


if __name__ == "__main__":
    main()
