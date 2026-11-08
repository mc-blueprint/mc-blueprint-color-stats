"""全本番promptを固定公開3枚で推論する。DB接続・既存artifact更新はしない。"""

import argparse
import fcntl
import os
import time
from pathlib import Path

import numpy as np
from bench.issue73.evaluate import digest, read, write
from bench.issue118.smoke import gpu_processes
from bench.issue130.diagnose import VARIANTS, policy, stages, verify
from PIL import Image

from colorstats.analyze import region_policy, segment_models
from colorstats.analyze.segment import _digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("models", "inputs", "freeze", "output", "slot"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    spec = read(args.freeze)
    verify(spec)
    # hostごとの協調lock。別タスクの無協調GPU利用も毎画像前後に検出する。
    with args.slot.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if gpu_processes():
            raise RuntimeError("別のGPU処理があるため開始しません")
        if region_policy.model_configuration(args.models / "oneformer") != spec["legacy_model"]:
            raise ValueError("OneFormerの固定重みSHAが一致しません")
        models = {}
        for name, files in spec["models"].items():
            for filename, sha in files.items():
                if digest(args.models / name / filename) != sha:
                    raise ValueError("候補モデルの固定SHAが一致しません")
            models[name] = {"files": files}
        models["oneformer"] = spec["legacy_model"]
        manifest = read(args.inputs / "inputs.json")
        args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
        write(args.output / "freeze.json", {"base_freeze_sha256": digest(args.freeze),
              "input_manifest_sha256": digest(args.inputs / "inputs.json"),
              "prompts": spec["production_prompts"], "policy_hash": _digest(policy()),
              "before_predictions": True})
        records = []
        for row in manifest["rows"]:
            if any(pid != os.getpid() for pid, _ in gpu_processes()):
                raise RuntimeError("別のGPU処理を検出しました")
            path = args.inputs / row["file"]
            if digest(path) != row["sha256"]:
                raise ValueError("smoke入力SHAが一致しません")
            with Image.open(path) as source:
                image = source.convert("RGB")
            started = time.monotonic()
            payload = {"model_paths": {name: str(args.models / name) for name in models},
                       "prompts": spec["production_prompts"]}
            parameters = {"models": models, "threshold": 0.35, "text_threshold": 0.25}
            # OOMを含む例外は握り潰さず、その時点で停止する。
            semantic, candidates, metrics = segment_models.predict_regions(
                image, payload, parameters)
            values = {}
            for variant in VARIANTS:
                predictions, _, diagnostics = stages(
                    semantic, candidates, list(payload["prompts"]), variant)
                count = np.zeros(semantic.shape, dtype=np.uint16)
                for _, mask in predictions["effective"]:
                    count += mask
                if np.any(count > 1) or np.any((count > 0) & np.isin(semantic, [2, 12])):
                    raise ValueError("有効領域に競合またはsky/person混入があります")
                values[variant] = {**diagnostics, "effective_pixels": int((count > 0).sum()),
                                   "pixels": int(count.size)}
            records.append({"seconds": time.monotonic() - started,
                            "runtime": metrics, "variants": values})
            write(args.output / f"record-{len(records)}.json", records[-1])
            if any(pid != os.getpid() for pid, _ in gpu_processes()):
                raise RuntimeError("実行中に別のGPU処理を検出しました")
        import torch

        write(args.output / "summary.json", {"gpu": torch.cuda.get_device_name(),
              "images": len(records), "freeze_sha256": digest(args.freeze),
              "policy_hash": _digest(policy()), "production_prompt_count": len(
                  spec["production_prompts"]), "batch_size": 1,
              "seconds": sum(row["seconds"] for row in records),
              "peak_allocated_bytes": max(max(row["runtime"]["peak_allocated_bytes"],
                                              row["runtime"]["oneformer_peak_allocated_bytes"])
                                          for row in records),
              "peak_reserved_bytes": max(max(row["runtime"]["peak_reserved_bytes"],
                                             row["runtime"]["oneformer_peak_reserved_bytes"])
                                         for row in records),
              "records": records, "quality_eligible": False,
              "limitation": "公開3枚の適合検証。全本番promptの全件品質保証ではない。"})


if __name__ == "__main__":
    main()
