"""固定入力のGPU smoke。DBに接続せず、画像別の記録はprivate出力へ保存する。"""

import argparse
import json
import os
import socket
import subprocess
import threading
import time
import traceback
import uuid
import weakref
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

from colorstats.analyze import region_policy, segment, segment_models
from colorstats.queue.core import Claim, NonRetryableError


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")
    path.chmod(0o600)


def gpu_processes():
    text = subprocess.check_output([
        "nvidia-smi", "--query-compute-apps=pid,used_gpu_memory", "--format=csv,noheader,nounits",
    ], text=True)
    return [(int(row.split(",")[0]), int(row.split(",")[1])) for row in text.splitlines()
            if row.strip()]


def comparisons(prepared, policy, building_labels):
    """同じ推論のraw候補と有効maskを比較する。skyはOneFormer参照であり画素GTではない。"""
    with Image.open(policy["semantic"]["path"]) as image:
        semantic = np.array(image)
    raw_building = np.zeros(semantic.shape, dtype=bool)
    raw_terrain = raw_building.copy()
    effective_building = raw_building.copy()
    effective_terrain = raw_building.copy()
    for row in prepared.data["regions"]:
        with Image.open(row["mask_path"]) as image:
            mask = np.asarray(image) != 0
        if row["label"] in building_labels:
            raw_building |= mask
        if row["label"] in region_policy.TERRAIN:
            raw_terrain |= mask
    for role, record in policy["roles"].items():
        with Image.open(record["path"]) as image:
            mask = np.asarray(image) != 0
        if role == "real_building/wall" or (
            role.startswith("real_building/") and role.split("/", 1)[1] in building_labels
        ):
            effective_building |= mask
        if role.startswith("real_terrain/"):
            effective_terrain |= mask
    sky = semantic == 2
    return {"pixels": int(semantic.size), "sky_pixels": int(sky.sum()),
            "raw_building_pixels": int(raw_building.sum()),
            "effective_building_pixels": int(effective_building.sum()),
            "sky_building_before": int((raw_building & sky).sum()),
            "sky_building_after": int((effective_building & sky).sum()),
            "building_terrain_before": int((raw_building & raw_terrain).sum()),
            "building_terrain_after": int((effective_building & effective_terrain).sum()),
            "effective_pixels": policy["metrics"]["effective_pixels"],
            "void_pixels": policy["metrics"]["void_pixels"]}


def summarize(records):
    """画像IDや入力SHAを含めず、件数・画素率・実行性能だけを集約する。"""
    successful = [row for row in records if row["status"] == "succeeded"]
    keys = ("pixels", "sky_pixels", "raw_building_pixels", "effective_building_pixels",
            "sky_building_before", "sky_building_after", "building_terrain_before",
            "building_terrain_after", "effective_pixels", "void_pixels")
    counts = {key: sum(row["comparison"][key] for row in successful) for key in keys}
    denominator = counts["pixels"]
    rates = {key + "_image_rate": counts[key] / denominator if denominator else None
             for key in ("sky_building_before", "sky_building_after", "building_terrain_before",
                         "building_terrain_after", "effective_pixels", "void_pixels")}
    known = {}
    for name, metric in (("sky_building", "sky_building"),
                         ("overlap_reported", "building_terrain")):
        subset = [row for row in successful if row["known"][name]]
        known[name] = {"cases": len(subset),
                       "positive_before": sum(row["comparison"][metric + "_before"] > 0
                                              for row in subset),
                       "positive_after": sum(row["comparison"][metric + "_after"] > 0
                                             for row in subset)}
    return {"attempted": len(records), "succeeded": len(successful),
            "oom": sum(row["status"] == "oom" for row in records),
            "failed": sum(row["status"] == "failed" for row in records),
            "counts": counts, "rates": rates, "known_cases": known,
            "total_seconds": sum(row["seconds"] for row in records),
            "peak_allocated_bytes": max((max(row["metrics"]["peak_allocated_bytes"],
                                              row["metrics"]["oneformer_peak_allocated_bytes"])
                                         for row in successful), default=None),
            "oneformer_peak_allocated_bytes": max((row["metrics"]["oneformer_peak_allocated_bytes"]
                                                   for row in successful), default=None),
            "candidates_peak_allocated_bytes": max((row["metrics"]["peak_allocated_bytes"]
                                                    for row in successful), default=None)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if gpu_processes():
        raise RuntimeError("GPU計算プロセスがあるため開始しません")
    args.output.mkdir(parents=True, exist_ok=False)
    args.output.chmod(0o700)
    selection = json.loads((args.inputs / "selection.json").read_text())
    root = Path(__file__).resolve().parents[2]
    settings = yaml.safe_load((root / "configs/segment_stats.yaml").read_text())
    parts = yaml.safe_load((root / "taxonomy/parts.yaml").read_text())
    building = {label for group, labels in parts["groups"].items() if group != "context"
                for label in labels}
    import torch
    from transformers import (
        AutoModelForZeroShotObjectDetection,
        OneFormerForUniversalSegmentation,
        Sam2Model,
    )

    before = gpu_processes()
    if before:
        raise RuntimeError("GPUの空きを再確認できません")
    monitoring = []
    errors = []
    stopped = threading.Event()

    def monitor():
        while not stopped.is_set():
            try:
                monitoring.append({"time": time.monotonic(), "processes": gpu_processes()})
            except Exception as error:
                errors.append(type(error).__name__)
            stopped.wait(0.5)

    thread = threading.Thread(target=monitor)
    thread.start()
    release_events = []
    candidate_events = []
    original_unload = segment_models._unload
    original_predict = segment_models.predict
    model_refs = []
    factories = [OneFormerForUniversalSegmentation, AutoModelForZeroShotObjectDetection, Sam2Model]
    loaders = [factory.from_pretrained for factory in factories]
    for factory, loader in zip(factories, loaders, strict=True):
        def observed_loader(*arguments, _loader=loader, **kwargs):
            model = _loader(*arguments, **kwargs)
            model_refs.extend(weakref.ref(module) for module in model.modules())
            return model

        factory.from_pretrained = observed_loader

    def unload():
        original_unload()
        release_events.append({"time": time.monotonic(),
                               "allocated": torch.cuda.memory_allocated(),
                               "reserved": torch.cuda.memory_reserved(),
                               "live_modules": sum(ref() is not None for ref in model_refs)})

    def candidates(*arguments, **kwargs):
        allocated = torch.cuda.memory_allocated()
        live = sum(ref() is not None for ref in model_refs)
        candidate_events.append({"allocated_before_candidates": allocated, "live_modules": live})
        if live:
            raise RuntimeError("OneFormer解放前に候補モデルをロードしません")
        return original_predict(*arguments, **kwargs)

    segment_models._unload = unload
    segment_models.predict = candidates
    records = []
    try:
        for row in selection["assets"]:
            if any(pid != os.getpid() for pid, _ in gpu_processes()):
                raise RuntimeError("別のGPU計算プロセスを検出しました")
            image_path = args.inputs / row["file"]
            if segment._hash(image_path) != row["input_sha256"]:
                raise ValueError("smoke入力のSHAが変わっています")
            payload = {**settings["segment"], "method": region_policy.METHOD,
                       "model_paths": {name: str(args.models / name)
                                       for name in ("sam2", "dino", "oneformer")},
                       "input_path": str(image_path), "input_sha256": row["input_sha256"],
                       "input_run_id": row["input_run_id"],
                       "output_path": str(args.output / row["sample_id"] / "segment.json"),
                       "license_class": row["license_class"],
                       "taxonomy_version": row["taxonomy_version"],
                       "taxonomy_path": str(root / "taxonomy")}
            started = time.perf_counter()
            record = {"sample_id": row["sample_id"], "known": row["known"],
                      "input_sha256": row["input_sha256"]}
            try:
                claim = Claim(uuid.uuid4(), uuid.uuid4(), "segment", uuid.UUID(row["asset_id"]),
                              segment.config_hash(payload), payload, 1, datetime.now(UTC))
                prepared = segment.prepare(claim)
                for temporary, target in prepared.files:
                    if target.exists():
                        raise FileExistsError(target)
                    temporary.replace(target)
                policy = prepared.data["region_policy"]
                region_policy.load_masks({**payload, "region_run_id": str(claim.id),
                                          "region_policy": {**policy, "run_id": str(claim.id)}})
                record.update(status="succeeded", metrics=prepared.data["metrics"],
                              comparison=comparisons(prepared, policy, building))
            except Exception as error:
                record.update(status="oom" if isinstance(error, NonRetryableError)
                              and region_policy.OOM_REASON in str(error) else "failed",
                              error_type=type(error).__name__, error=str(error))
                (args.output / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
            record["seconds"] = time.perf_counter() - started
            records.append(record)
            save(args.output / "records.json", records)
            print(json.dumps({"completed": len(records), "status": record["status"]}), flush=True)
            if record["status"] != "succeeded":
                break
    finally:
        segment_models._unload = original_unload
        segment_models.predict = original_predict
        original_unload()
        for factory, loader in zip(factories, loaders, strict=True):
            factory.from_pretrained = loader
        stopped.set()
        thread.join()
    save(args.output / "monitor.json", {"samples": monitoring, "errors": errors,
                                       "releases": release_events,
                                       "candidate_starts": candidate_events})
    summary = summarize(records)
    summary.update(host=socket.gethostname(), seed=selection["seed"],
                   gpu=torch.cuda.get_device_name(),
                   gpu_total_bytes=torch.cuda.get_device_properties(0).total_memory,
                   max_foreign_gpu_processes=max((sum(pid != os.getpid() for pid, _ in sample[
                       "processes"]) for sample in monitoring), default=0),
                   observed_process_peak_mib=max((memory for sample in monitoring
                                                  for pid, memory in sample["processes"]
                                                  if pid == os.getpid()), default=None),
                   unload_checks=len(release_events),
                   unload_live_module_checks=sum(row["live_modules"] != 0
                                                 for row in release_events),
                   candidate_start_checks=len(candidate_events),
                   candidate_start_live_module_checks=sum(row["live_modules"] != 0
                                                          for row in candidate_events),
                   runtime_workspace_peak_bytes=max((row["allocated_before_candidates"]
                                                     for row in candidate_events), default=0),
                   monitor_errors=len(errors),
                   oneformer_files_verified=len(region_policy.MODEL_FILES))
    save(args.output / "summary.json", summary)
    if (summary["succeeded"] != len(selection["assets"]) or summary["max_foreign_gpu_processes"]
            or summary["unload_live_module_checks"] or summary["monitor_errors"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
