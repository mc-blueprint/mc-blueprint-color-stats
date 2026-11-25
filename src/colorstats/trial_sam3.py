"""SAM3専用Pythonで直接実行するworker。通常アプリやDBをimportしない。"""

import argparse
import json
import os
import time
from pathlib import Path

from colorstats.trial_native_common import (
    TEXT_PROMPTS,
    box_from_mask,
    check_environment,
    failure_code,
    load_image,
    save_phase,
    verify_files,
    write_private,
)

SAM3_MODEL = ("facebook/sam3", "b7296bc5016065f0d6e772c058601de3da6e932b")


def sam3(spec, image):
    import torch
    from sam3.model.sam3_image_processor import Sam3Processor
    from sam3.model_builder import build_sam3_image_model

    model = build_sam3_image_model(
        checkpoint_path=str(Path(spec["model_path"]) / "sam3.pt"),
        load_from_HF=False,
    ).float()
    processor = Sam3Processor(model, confidence_threshold=0.5)
    masks = []
    with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=torch.bfloat16):
        for part, prompt in TEXT_PROMPTS.items():
            output = processor.set_text_prompt(prompt=prompt, state=processor.set_image(image))
            for predicted in output["masks"]:
                values = predicted.detach().cpu().numpy().squeeze() != 0
                if values.shape != (image.height, image.width):
                    raise ValueError("SAM3の画像座標が一致しません")
                if values.any():
                    masks.append((part, box_from_mask(values), values))
            if len(masks) > 24:
                raise ValueError("領域数上限です")
    return "unsupported", masks


def run(spec, directory):
    """固定SAM3構成を検証して推論し、既存phase出力と二値PNGを保存する。"""
    if (
        spec["configuration_id"] != "E"
        or (spec["model"]["repo"], spec["model"]["revision"]) != SAM3_MODEL
        or spec["contract"]["precision"] != "FP32+BF16-autocast"
    ):
        raise ValueError("固定SAM3構成が一致しません")
    check_environment(spec, sam3=True)
    verify_files(Path(spec["model_path"]), spec["model"]["files"])
    image = load_image(spec, directory)
    started = time.monotonic()
    scene, masks = sam3(spec, image)
    save_phase(spec, directory, "sam3", scene, masks, 0, started)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory.resolve()
    spec = json.loads((directory / "request.json").read_text())
    for key in ("HF_HUB_DISABLE_TELEMETRY", "DO_NOT_TRACK", "HF_HUB_OFFLINE"):
        os.environ[key] = "1"
    try:
        run(spec, directory)
    except Exception as error:
        write_private(
            directory / "failure.json", json.dumps({"reason_code": failure_code(error)}).encode()
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
