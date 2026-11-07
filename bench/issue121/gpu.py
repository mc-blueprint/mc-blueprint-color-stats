"""同じ公開入力3枚で両GPUの時間・VRAM・単独工程を測る。所有画像は使わない。"""

import argparse
import time
from pathlib import Path

import numpy as np
from bench.issue73.evaluate import digest, read, write
from bench.issue81.evaluate import text_digest
from PIL import Image

from colorstats.analyze import region_policy, segment_models


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = read(args.inputs / "inputs.json")
    spec = read(args.inputs / "freeze.json")
    if region_policy.model_configuration(args.models / "oneformer") != spec["oneformer"]:
        raise ValueError("OneFormerの固定重みと不一致です")
    models = {}
    for name, files in spec["models"].items():
        for filename, expected in files.items():
            if digest(args.models / name / filename) != expected:
                raise ValueError("DINO/SAM2の固定重みと不一致です")
        models[name] = {"files": files}
    models["oneformer"] = spec["oneformer"]
    for row in manifest["rows"]:
        if digest(args.inputs / row["file"]) != row["sha256"]:
            raise ValueError("固定公開入力のSHAと不一致です")
    args.output.mkdir(parents=True, exist_ok=False)
    write(args.output / "freeze.json", {
        "inputs_sha256": digest(args.inputs / "inputs.json"),
        "base_freeze_sha256": digest(args.inputs / "freeze.json"),
        "code_sha256": text_digest(Path(__file__)), "before_predictions": True})
    parameters = {"models": models, "threshold": 0.35, "text_threshold": 0.25}
    payload = {"model_paths": {name: str(args.models / name) for name in models},
               "prompts": read(Path("bench/issue73/plan.json"))["source_settings"]["cmp"][
                   "prompts"]}
    records = []
    for row in manifest["rows"]:
        started = time.monotonic()
        with Image.open(args.inputs / row["file"]) as source:
            image = source.convert("RGB")
        semantic, candidates, metrics = segment_models.predict_regions(image, payload, parameters)
        masks, _, policy_metrics = region_policy.constrain(
            semantic, candidates, set(payload["prompts"]))
        count = np.zeros(semantic.shape, dtype=np.uint16)
        for mask in masks.values():
            count += mask
        if np.any(count > 1):
            raise ValueError("有効役割に交差があります")
        records.append({"seconds": time.monotonic() - started, "runtime": metrics,
                        "policy": policy_metrics})
    import torch

    write(args.output / "summary.json", {
        "gpu": torch.cuda.get_device_name(), "images": len(records),
        "input_manifest_sha256": digest(args.inputs / "inputs.json"),
        "total_seconds": sum(row["seconds"] for row in records),
        "peak_allocated_bytes": max(max(row["runtime"]["peak_allocated_bytes"],
                                        row["runtime"]["oneformer_peak_allocated_bytes"])
                                    for row in records),
        "peak_reserved_bytes": max(max(row["runtime"]["peak_reserved_bytes"],
                                       row["runtime"]["oneformer_peak_reserved_bytes"])
                                   for row in records),
        "records": records, "policy_hash": region_policy.policy_hash(),
        "quality_eligible": False,
        "limitation": "公開3枚の両GPU適合・性能。全件の8GB適合や品質の保証ではない。"})


if __name__ == "__main__":
    main()
