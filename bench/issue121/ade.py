"""ADE全validationのsemantic診断。部位候補の合格判定・所有画像の保証には使わない。"""

import argparse
import hashlib
import io
import time
import zipfile
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import numpy as np
from bench.issue73.evaluate import digest, read, write
from bench.issue81.evaluate import text_digest
from bench.issue121.public import verify_spec
from PIL import Image

from colorstats.analyze import region_policy, segment_models
from colorstats.segmentation_evaluation import scores


def confusion(truth, semantic):
    """行が注釈ID 0〜150、列がモデルID 0〜149の計数。0行は別保存して採否から除く。"""
    if (truth.shape != semantic.shape or not np.isin(truth, range(151)).all()
            or not np.isin(semantic, range(150)).all()):
        raise ValueError("ADE注釈ID・モデルIDまたは座標が不正です")
    return np.bincount(truth.astype(np.int64).ravel() * 150 + semantic.ravel(),
                       minlength=151 * 150).reshape(151, 150)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    spec = read(args.freeze)
    verify_spec(spec)
    path = args.data / "ADEChallengeData2016.zip"
    if digest(path) != spec["archives"][path.name]:
        raise ValueError("固定ADE ZIPのSHAが不一致です")
    if region_policy.model_configuration(args.models / "oneformer") != spec["oneformer"]:
        raise ValueError("固定OneFormerのSHAが不一致です")
    args.output.mkdir(parents=True, exist_ok=False)
    args.output.chmod(0o700)
    with zipfile.ZipFile(path) as archive:
        names = sorted(name for name in archive.namelist()
                       if "/images/validation/" in name and name.endswith(".jpg"))
        if len(names) != 2000:
            raise ValueError("ADE validationの件数が不一致です")
        rows = []
        for name in names:
            annotation = name.replace("/images/", "/annotations/").replace(".jpg", ".png")
            rows.append({"image": name, "annotation": annotation,
                         "sha256": hashlib.sha256(archive.read(name)).hexdigest(),
                         "truth_sha256": hashlib.sha256(archive.read(annotation)).hexdigest()})
        manifest = {"rows": rows, "frozen_at": datetime.now(UTC).isoformat(),
                    "base_freeze_sha256": digest(args.freeze),
                    "code_sha256": text_digest(Path(__file__)),
                    "scope": "ADE学習済みモデルの全validation診断。部位mask品質とは別。",
                    "size": 512, "truth_resize": "nearest", "quality_eligible": False}
        write(args.output / "input-freeze.json", manifest)
        import torch
        from transformers import OneFormerForUniversalSegmentation
        from transformers.models.oneformer.modeling_oneformer import OneFormerSinePositionEmbedding

        versions = {name: version(name) for name in ("torch", "transformers", "Pillow")}
        if versions["torch"].split("+")[0] != "2.11.0" or versions["transformers"] != "4.57.6":
            raise ValueError("固定GPU実行版が不一致です")
        started = time.monotonic()
        segment_models._unload()
        torch.cuda.reset_peak_memory_stats()
        processor = segment_models._oneformer_processor(args.models / "oneformer")
        processor.image_processor.size = {key: spec["transform"][key]
                                          for key in ("shortest_edge", "longest_edge")}
        processor.image_processor._max_size = spec["transform"]["longest_edge"]
        model = OneFormerForUniversalSegmentation.from_pretrained(
            args.models / "oneformer", local_files_only=True, weights_only=True).eval().to("cuda")
        segment_models._uncache_positions(model, OneFormerSinePositionEmbedding)
        region_policy.validate_labels({str(k): v for k, v in model.config.id2label.items()})
        matrix = np.zeros((151, 150), dtype=np.int64)
        try:
            for index, row in enumerate(rows, 1):
                image = Image.open(io.BytesIO(archive.read(row["image"]))).convert("RGB")
                image.thumbnail((512, 512), Image.Resampling.LANCZOS)
                truth = np.asarray(Image.open(io.BytesIO(archive.read(row["annotation"]))).resize(
                    image.size, Image.Resampling.NEAREST))
                torch.manual_seed(0)
                with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
                    inputs = processor(images=image, task_inputs=["semantic"],
                                       return_tensors="pt").to("cuda")
                    outputs = model(**inputs)
                    semantic = processor.post_process_semantic_segmentation(
                        outputs, target_sizes=[(image.height, image.width)],
                    )[0].cpu().numpy().astype(np.uint8)
                matrix += confusion(truth, semantic)
                del inputs, outputs
                if index % 100 == 0:
                    print({"images": index, "seconds": time.monotonic() - started}, flush=True)
            runtime = {"gpu": torch.cuda.get_device_name(), "versions": versions,
                       "images": len(rows), "seconds": time.monotonic() - started,
                       "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
                       "peak_reserved_bytes": torch.cuda.max_memory_reserved()}
        finally:
            del model, processor
            segment_models._unload()
    values = {}
    for annotation_id in range(1, 151):
        tp = int(matrix[annotation_id, annotation_id - 1])
        values[str(annotation_id)] = scores({
            "tp": tp, "fp": int(matrix[1:, annotation_id - 1].sum()) - tp,
            "fn": int(matrix[annotation_id].sum()) - tp})
    write(args.output / "summary.json", {
        "input_freeze_sha256": digest(args.output / "input-freeze.json"),
        "runtime": runtime, "confusion": matrix.tolist(), "classes": values,
        "truth_void_pixels": int(matrix[0].sum()),
        "nonvoid_pixels": int(matrix[1:].sum()), "quality_eligible": False,
        "scope": "全2000枚。ADE学習済みsemanticモデルの診断であり、所有画像の独立保証ではない。"})


if __name__ == "__main__":
    main()
