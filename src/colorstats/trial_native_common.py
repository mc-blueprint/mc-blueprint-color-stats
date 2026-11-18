"""通常環境とSAM3専用環境で共有する、DB依存のない実行処理。"""

import hashlib
import importlib.metadata
import io
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image


def sha(content):
    return hashlib.sha256(content).hexdigest()


def private_path(root, relative):
    """試行root内の通常ファイルだけを解決し、symlink・脱出を拒否する。"""
    root = Path(root)
    path = root / relative
    if (
        Path(relative).is_absolute()
        or ".." in Path(relative).parts
        or "\\" in str(relative)
        or path.resolve() != path
        or not path.is_relative_to(root)
    ):
        raise ValueError("試行内の相対パスが必要です")
    return path


def write_private(path, content):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
        stream.write(content)


def verify_files(directory, files):
    """事前に固定したファイル一覧のSHAを照合する。初回算出値を正解にしない。"""
    if not files:
        raise ValueError("重み・設定・remote codeの固定一覧が必要です")
    for record in files:
        if sha(private_path(directory, record["file"]).read_bytes()) != record["sha256"]:
            raise ValueError("取得物のSHAが一致しません")


def box_from_mask(mask):
    y, x = np.nonzero(mask)
    return [
        float(x.min() / mask.shape[1]),
        float(y.min() / mask.shape[0]),
        float((x.max() + 1) / mask.shape[1]),
        float((y.max() + 1) / mask.shape[0]),
    ]


def failure_code(error):
    """外部へ例外の原文を出さず、停止判断に必要な分類だけを残す。"""
    if type(error).__name__ == "OutOfMemoryError":
        return "oom"
    if isinstance(error, (ImportError, NotImplementedError)):
        return "unsupported"
    if isinstance(error, subprocess.TimeoutExpired):
        return "timeout"
    message = str(error)
    for word, code in (
        ("context", "context_limit"),
        ("打ち切", "truncated"),
        ("領域数", "region_limit"),
        ("GPU", "vram_limit"),
    ):
        if word in message:
            return code
    return "invalid_output"


TEXT_PROMPTS = {
    "wall": "exterior building wall excluding roofs windows and doors",
    "roof": "visible building roof excluding walls",
    "window": "whole window including glass and surrounding frame",
    "window_glass": "window glass excluding the surrounding frame",
    "window_frame": "frame surrounding window glass excluding glass",
    "door": "visible entrance door excluding the surrounding wall",
}


CODE_FILES = ("trial_native.py", "trial_native_common.py", "trial_sam3.py", "trial_paths.json")
CONTROLLER_LOCK = "/opt/colorstats/locks/controller.lock"
SAM3_LOCK = "/opt/colorstats/locks/sam3.lock"
_PATHS = json.loads(Path(__file__).with_name("trial_paths.json").read_text(encoding="utf-8"))
CONTROLLER_PYTHON = _PATHS["CONTROLLER_PYTHON"]
SAM3_PYTHON = _PATHS["SAM3_PYTHON"]
CODE_PATH = _PATHS["PYTHONPATH"]


def python_command(*, sam3=False):
    """SSHと子workerで、固定Pythonとコード探索パスを明示した引数を返す。"""
    if sam3:
        executable, module = SAM3_PYTHON, "colorstats.trial_sam3"
    else:
        executable, module = CONTROLLER_PYTHON, "colorstats.trial_native"
    return ["/usr/bin/env", f"PYTHONPATH={CODE_PATH}", executable, "-m", module]


def code_files():
    """配備する実行コード全体を、構成参照へ結ぶ。"""
    return {name: sha(Path(__file__).with_name(name).read_bytes()) for name in CODE_FILES}


def check_environment(spec, *, sam3=False):
    """コード・環境別lock・宣言版を照合する。GPUとDBには接続しない。"""
    if any(spec[k]["license_confirmed"] is not True for k in ("model", "segmenter")):
        raise PermissionError("ライセンス確認が必要です")
    runtime = spec["runtime"]
    if runtime["code_files"] != code_files():
        raise ValueError("実行コードのSHAが一致しません")
    environment = (
        runtime["sam3"] if sam3 else {"versions": spec["versions"], "lock": runtime["lock"]}
    )
    if sha(Path(environment["lock"]["file"]).read_bytes()) != environment["lock"]["sha256"]:
        raise ValueError("依存lockのSHAが一致しません")
    for name, version in environment["versions"].items():
        if importlib.metadata.version(name) != version:
            raise ValueError("固定依存版が一致しません")


def load_image(spec, directory):
    """固定入力と最新の短い期限を検査し、元座標のRGB画像を返す。"""
    content = (directory / "input.png").read_bytes()
    image = Image.open(io.BytesIO(content)).convert("RGB")
    if max(image.size) > 1024 or sha(content) != spec["input_sha256"]:
        raise ValueError("固定入力のSHA・長辺が一致しません")
    check_deadline(spec, directory)
    return image


def check_deadline(spec, directory):
    until = datetime.fromisoformat(spec["external_deadline"])
    update = directory / "deadline.json"
    if update.exists():
        until = min(
            until, datetime.fromisoformat(json.loads(update.read_text())["external_deadline"])
        )
    if until <= datetime.now(UTC):
        raise ValueError("外部保持期限が切れました")


def environment_reference(versions, runtime):
    """#141の環境参照へ、親とE専用のlock・宣言版を含める。"""
    return {"versions": versions, "lock": runtime["lock"], "sam3": runtime.get("sam3")}


def save_phase(spec, directory, name, scene, masks, tokens, started):
    """同じ座標・二値PNG・計測値のphase出力を両環境で保存する。"""
    import torch

    check_deadline(spec, directory)
    regions = []
    for i, (part, box, mask) in enumerate(masks):
        stream = io.BytesIO()
        Image.fromarray(np.asarray(mask, dtype="uint8") * 255).save(stream, format="PNG")
        check_deadline(spec, directory)
        name_mask = f"mask-{i:02}.png"
        write_private(directory / name_mask, stream.getvalue())
        regions.append(
            {
                "part": part,
                "box": box,
                "mask": {
                    "file": name_mask,
                    "sha256": sha(stream.getvalue()),
                },
            }
        )
    peaks = [torch.cuda.max_memory_reserved(i) / 1048576 for i in range(torch.cuda.device_count())]
    if spec["configuration_id"] in "ABC" and any(
        torch.cuda.get_device_properties(i).total_memory / 1048576 - peak < 4096
        for i, peak in enumerate(peaks)
    ):
        raise ValueError("GPUごとの4GiB余裕が不足しています")
    check_deadline(spec, directory)
    write_private(
        directory / f"{name}-output.json",
        json.dumps(
            {
                "scene": scene,
                "regions": regions,
                "input_tokens": tokens,
                "peak_vram_mib": max(peaks),
                "elapsed_seconds": time.monotonic() - started,
            }
        ).encode(),
    )
