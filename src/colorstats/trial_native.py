"""承認後の専用containerで使うnative推論。通常importはGPUを要求しない。"""

import argparse
import json
import os
import re
import signal
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image

from colorstats.api_budget import digest
from colorstats.trial_inputs import SCENES, sha, write_private
from colorstats.trial_native_common import (
    TEXT_PROMPTS,
    box_from_mask,
    check_environment,
    environment_reference,
    failure_code,
    load_image,
    python_command,
    save_phase,
    verify_files,
)
from colorstats.trial_results import PARTS

MODELS = {
    "A": ("Qwen/Qwen3-VL-8B-Instruct", "0c351dd01ed87e9c1b53cbc748cba10e6187ff3b"),
    "B": ("Qwen/Qwen3-VL-32B-Instruct", "0cfaf48183f594c314753d30a4c4974bc75f3ccb"),
    "C": ("Qwen/Qwen2.5-VL-72B-Instruct-AWQ", "c8b87d4b81f34b6a147577a310d7e75f0698f6c2"),
    "D": ("ByteDance/Sa2VA-8B", "902b049acb12eb68454abf4e51ab1e23d1bc9efa"),
    "E": ("facebook/sam3", "b7296bc5016065f0d6e772c058601de3da6e932b"),
}
SAM2 = ("facebook/sam2.1-hiera-large", "665f8e2ad61cf5f53d65644ff27c8ee525124610")
LIMITS = {"batch": 1, "long_edge": 1024, "context": 8192, "answer": 1536, "regions": 24}
PROMPT = (
    "写真に見える部分だけを答えてください。隠れた面は補わず、不明ならunknownまたは空配列。"
    "JSONだけで返し、sceneとregionsを持たせてください。sceneはsingle（屋外の主対象1棟）、"
    "interior（屋内）、group（建物群）、gate（門）、closeup（接写）、terrain（地形）、unknown。"
    "regionsの各要素はpartとbox。boxは画像全体を0から1とした左上x,y,右下x,y。"
    "同じ部位が複数なら個別に答え、合計24領域まで。窓全体と窓ガラス・窓枠の重なりは許します。"
    + " ".join(f"{key}（{label}）は{definition}" for key, (label, definition) in PARTS.items())
)


def checked_boxes(value):
    """native応答の部位・箱を検査し、上限超過や補正が必要な結果を拒否する。"""
    if set(value) != {"scene", "regions"} or value["scene"] not in SCENES:
        raise ValueError("nativeの場面・領域形式が不正です")
    if not isinstance(value["regions"], list) or len(value["regions"]) > 24:
        raise ValueError("nativeの領域数上限です")
    for region in value["regions"]:
        if set(region) != {"part", "box"} or region["part"] not in PARTS:
            raise ValueError("nativeの部位が不正です")
        box = region["box"]
        if (
            not isinstance(box, list)
            or len(box) != 4
            or any(type(v) not in {int, float} or not 0 <= v <= 1 for v in box)
            or box[0] >= box[2]
            or box[1] >= box[3]
        ):
            raise ValueError("nativeの箱が不正です")
    return value


def provision(spec, directory):
    """固定revisionの必要ファイルを画像転送前に取得し、既知のSHAと照合する。"""
    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=spec["repo"],
        revision=spec["revision"],
        allow_patterns=[r["file"] for r in spec["files"]],
        local_dir=str(directory),
    )
    verify_files(directory, spec["files"])


def environment(spec):
    check_environment(spec)
    if digest(spec["runtime"]["code_files"]) != spec["contract"]["code_sha256"]:
        raise ValueError("実行コードの固定参照が一致しません")
    if (
        digest(environment_reference(spec["versions"], spec["runtime"]))
        != spec["contract"]["environment_sha256"]
    ):
        raise ValueError("実行環境の固定参照が一致しません")


def qwen(spec, image):
    from transformers import AutoProcessor
    from vllm import LLM, SamplingParams

    directory = spec["model_path"]
    processor = AutoProcessor.from_pretrained(directory, local_files_only=True)
    messages = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": PROMPT}]}]
    prompt = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[prompt], images=[image], return_tensors="pt")
    tokens = int(inputs["input_ids"].shape[-1])
    if tokens + LIMITS["answer"] > LIMITS["context"]:
        raise ValueError("画像token込みのcontext上限です")
    llm = LLM(
        model=directory,
        tokenizer=directory,
        tensor_parallel_size=spec["gpu_count"],
        dtype="half" if spec["configuration_id"] == "C" else "bfloat16",
        quantization="awq" if spec["configuration_id"] == "C" else None,
        max_model_len=8192,
        max_num_seqs=1,
        limit_mm_per_prompt={"image": 1},
        gpu_memory_utilization=spec["memory_fraction"],
        seed=20261116,
    )
    response = llm.generate(
        [{"prompt": prompt, "multi_modal_data": {"image": image}}],
        SamplingParams(temperature=0, max_tokens=1536),
        use_tqdm=False,
    )[0]
    answer = response.outputs[0]
    if answer.finish_reason != "stop" or len(answer.token_ids) >= 1536:
        raise ValueError("回答が打ち切られました")
    return checked_boxes(json.loads(answer.text)), tokens


def sam2(spec, image, boxes):
    import torch
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    model = build_sam2(
        "configs/sam2.1/sam2.1_hiera_l.yaml",
        str(Path(spec["segmenter_path"]) / "sam2.1_hiera_large.pt"),
        device="cuda",
    ).float()
    predictor = SAM2ImagePredictor(model)
    with torch.inference_mode():
        predictor.set_image(np.asarray(image))
        masks = []
        for region in boxes["regions"]:
            box = np.array(region["box"]) * np.array([*image.size, *image.size])
            prediction, _, _ = predictor.predict(box=box, multimask_output=False)
            masks.append((region["part"], region["box"], prediction[0] > 0))
    return boxes["scene"], masks


def sa2va(spec, image):
    import torch
    from transformers import AutoModel, AutoTokenizer

    directory = spec["model_path"]
    model = (
        AutoModel.from_pretrained(
            directory,
            torch_dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
            use_flash_attn=True,
            trust_remote_code=True,
            local_files_only=True,
        )
        .eval()
        .cuda()
    )
    tokenizer = AutoTokenizer.from_pretrained(
        directory,
        trust_remote_code=True,
        use_fast=False,
        local_files_only=True,
    )
    model.preparing_for_generation(tokenizer, max_new_tokens=1536)
    original = model.generate
    usage = []

    def bounded_generate(*args, **kwargs):
        tokens = kwargs["input_ids"].shape[-1]
        if tokens + 1536 > 8192:
            raise ValueError("画像token込みのcontext上限です")
        result = original(*args, **kwargs)
        sequences = result.sequences if hasattr(result, "sequences") else result
        if sequences.shape[-1] >= 1536:
            raise ValueError("回答が打ち切られました")
        usage.append(int(tokens))
        return result

    model.generate = bounded_generate
    with torch.inference_mode():
        scene_result = model.predict_forward(
            image=image,
            text="<image>" + PROMPT,
            past_text="",
            mask_prompts=None,
            tokenizer=tokenizer,
        )
        scene = checked_boxes(json.loads(scene_result["prediction"]))["scene"]
        masks = []
        for part, prompt in TEXT_PROMPTS.items():
            answer = model.predict_forward(
                image=image,
                text="<image>Please segment " + prompt + ".",
                past_text="",
                mask_prompts=None,
                tokenizer=tokenizer,
            )
            for predicted in answer["prediction_masks"]:
                values = np.asarray(predicted).squeeze()
                if values.shape != (image.height, image.width):
                    raise ValueError("Sa2VAの画像座標が一致しません")
                if values.any():
                    masks.append((part, box_from_mask(values), values != 0))
            if len(masks) > 24:
                raise ValueError("領域数上限です")
    return scene, masks, max(usage)


def phase(spec, directory, name):
    """VLMとSAM2は別プロセスで実行し、CUDA常駐を分離する。"""
    environment(spec)
    image = load_image(spec, directory)
    tokens = 0
    started = time.monotonic()
    if name == "qwen":
        boxes, tokens = qwen(spec, image)
        write_private(directory / "boxes.json", json.dumps(boxes).encode())
        masks = []
        scene = boxes["scene"]
    elif name == "sam2":
        scene, masks = sam2(spec, image, json.loads((directory / "boxes.json").read_text()))
    elif name == "sa2va":
        scene, masks, tokens = sa2va(spec, image)
    else:
        raise ValueError("SAM3は専用workerで実行してください")
    save_phase(spec, directory, name, scene, masks, tokens, started)


def run_phases(spec, directory, phases):
    """vLLMの子workerも含め、専用GPUの使用量を外側から記録する。"""
    stopped = threading.Event()
    peaks, totals, failures = [], [], []

    def observe():
        while not stopped.is_set():
            try:
                result = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-gpu=memory.used,memory.total",
                        "--format=csv,noheader,nounits",
                    ],
                    check=True,
                    capture_output=True,
                    timeout=2,
                )
                samples = [
                    [float(n) for n in line.split(",")]
                    for line in result.stdout.decode().splitlines()
                ]
                if len(samples) != spec["gpu_count"]:
                    raise ValueError("GPU台数が一致しません")
                if not peaks:
                    peaks.extend(0 for _ in samples)
                    totals.extend(total for _, total in samples)
                for i, (used, _) in enumerate(samples):
                    peaks[i] = max(peaks[i], used)
            except (OSError, ValueError, subprocess.SubprocessError):
                failures.append("GPU使用量を確認できません")
                return
            stopped.wait(0.2)

    observer = threading.Thread(target=observe, name="trial-gpu-memory")
    observer.start()
    try:
        for name in phases:
            subprocess.run(
                [
                    *python_command(sam3=name == "sam3"),
                    "--directory",
                    str(directory),
                    *(["--phase", name] if name != "sam3" else []),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=min(
                    spec["image_timeout_seconds"],
                    max(
                        0.01,
                        (
                            datetime.fromisoformat(spec["external_deadline"]) - datetime.now(UTC)
                        ).total_seconds(),
                    ),
                ),
            )
    finally:
        stopped.set()
        observer.join()
    if failures or not peaks:
        raise RuntimeError("GPU使用量の記録が不足しています")
    if spec["configuration_id"] in "ABC" and any(
        t - p < 4096 for t, p in zip(totals, peaks, strict=True)
    ):
        raise ValueError("GPUごとの4GiB余裕が不足しています")
    return peaks


def expire_job(directory, deadline, group=None):
    """当試行の1画像分を期限で消す。Pod削除の確認とは別の補助処理。"""
    if directory.resolve() != directory or not re.fullmatch(
        r"/tmp/colorstats-[a-f0-9-]+/[A-E]_[a-f0-9]+/T[0-9]{3}", str(directory)
    ):
        raise ValueError("期限削除は当試行の画像ディレクトリに限ります")
    until = datetime.fromisoformat(deadline)
    if until.tzinfo is None:
        raise ValueError("外部保持期限にはタイムゾーンが必要です")
    if group is not None and (group <= 1 or group == os.getpgrp()):
        raise ValueError("期限監視自身とは別の試行プロセス群が必要です")
    while directory.exists():
        update = directory / "deadline.json"
        if update.exists():
            try:
                until = min(
                    until,
                    datetime.fromisoformat(json.loads(update.read_text())["external_deadline"]),
                )
            except (OSError, ValueError, TypeError, KeyError):
                until = datetime.now(UTC)
        if datetime.now(UTC) >= until:
            break
        time.sleep(min(1, max(0, (until - datetime.now(UTC)).total_seconds())))
    if directory.exists():
        if group is not None:
            try:
                os.killpg(group, signal.SIGTERM)
            except ProcessLookupError:
                pass
        names = {
            "input.png",
            "request.json",
            "output.json",
            "boxes.json",
            "failure.json",
            "deadline.json",
            "deadline-next.json",
        }
        names.update(f"mask-{i:02}.png" for i in range(24))
        names.update(f"{phase}-output.json" for phase in ("qwen", "sam2", "sa2va", "sam3"))
        for name in names:
            path = directory / name
            if path.is_file() and not path.is_symlink():
                path.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--phase", choices=["qwen", "sam2", "sa2va", "sam3", "prepare"])
    parser.add_argument("--expire-only", action="store_true")
    parser.add_argument("--expire-group", type=int)
    args = parser.parse_args()
    directory = args.directory.resolve()
    spec = json.loads((directory / "request.json").read_text())
    if args.expire_only:
        expire_job(directory, spec["external_deadline"], args.expire_group)
        return
    if args.phase is None:
        if os.getpgrp() != os.getpid():
            os.setsid()
        subprocess.Popen(
            [
                *python_command(),
                "--directory",
                str(directory),
                "--expire-only",
                "--expire-group",
                str(os.getpgrp()),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    environment(spec)
    for key in ("HF_HUB_DISABLE_TELEMETRY", "VLLM_NO_USAGE_STATS", "DO_NOT_TRACK"):
        os.environ[key] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1" if args.phase != "prepare" else "0"
    if args.phase == "prepare":
        provision(spec["model"], Path(spec["model_path"]))
        if spec["segmenter_path"] != spec["model_path"]:
            provision(spec["segmenter"], Path(spec["segmenter_path"]))
        write_private(directory / "prepared.json", b'{"verified": true}')
    elif args.phase:
        try:
            phase(spec, directory, args.phase)
        except Exception as error:
            write_private(
                directory / "failure.json",
                json.dumps({"reason_code": failure_code(error)}).encode(),
            )
            raise SystemExit(1) from None
    else:
        try:
            phases = (
                ["qwen", "sam2"]
                if spec["configuration_id"] in "ABC"
                else ["sa2va" if spec["configuration_id"] == "D" else "sam3"]
            )
            peaks = run_phases(spec, directory, phases)
            outputs = [
                json.loads((directory / f"{name}-output.json").read_text()) for name in phases
            ]
            result = outputs[-1]
            result["input_tokens"] = max(r["input_tokens"] for r in outputs)
            result["peak_vram_mib"] = max(max(peaks), max(r["peak_vram_mib"] for r in outputs))
            result["per_gpu_peak_vram_mib"] = peaks
            result["elapsed_seconds"] = sum(r["elapsed_seconds"] for r in outputs)
            result["status"] = "success"
        except (ValueError, subprocess.SubprocessError, RuntimeError) as error:
            failure = directory / "failure.json"
            reason = (
                json.loads(failure.read_text())["reason_code"]
                if failure.exists()
                else failure_code(error)
            )
            result = {
                "status": "truncated"
                if reason == "truncated"
                else "rejected"
                if reason == "unsupported"
                else "failed",
                "reason_code": reason,
                "scene": "unsupported" if spec["configuration_id"] == "E" else "unknown",
                "regions": [],
                "elapsed_seconds": 0,
                "peak_vram_mib": 0,
            }
        with Image.open(directory / "input.png") as image:
            size = list(image.size)
        result.update(
            {
                "attempt": spec["attempt"],
                "trial_id": spec["trial_id"],
                "configuration_id": spec["configuration_id"],
                "configuration_sha256": digest(spec["contract"]),
                "input_sha256": sha((directory / "input.png").read_bytes()),
                "size": size,
            }
        )
        write_private(directory / "output.json", json.dumps(result).encode())


if __name__ == "__main__":
    main()
