"""ローカルに配置済みの公式重みを使うGPU推論。重みの自動取得は行わない。"""

import time

import numpy as np

REPOSITORIES = {
    "sam2": "facebook/sam2.1-hiera-tiny",
    "dino": "IDEA-Research/grounding-dino-tiny",
}


def predict(image, method, paths, prompts, threshold, text_threshold):
    """(label, boolマスク, confidence)の列とGPU計測を返す。CUDA必須。

    モデルはこの呼出しだけ保持する。初期化と推論を個別に計測し、VRAMは
    初期化も含むPyTorch allocatorの最大値。OOM・依存不足はそのまま送出する。
    """
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("segmentの実モデル推論にはCUDAが必要です")
    torch.manual_seed(0)
    torch.cuda.reset_peak_memory_stats()
    start = time.perf_counter()
    if method != "sam2-dino":
        raise ValueError("methodはsam2-dinoです")
    runner = _sam2(paths)
    torch.cuda.synchronize()
    loaded = time.perf_counter()
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
        rows = runner(image, prompts, threshold, text_threshold)
    torch.cuda.synchronize()
    finished = time.perf_counter()
    return rows, {
        "load_seconds": loaded - start,
        "inference_seconds": finished - loaded,
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
        "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
        "gpu": torch.cuda.get_device_name(),
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "batch_size": 1,
    }


def _sam2(paths):
    from transformers import (
        AutoModelForZeroShotObjectDetection,
        AutoProcessor,
        Sam2Model,
        Sam2Processor,
    )

    processor = AutoProcessor.from_pretrained(paths["dino"], local_files_only=True)
    detector = AutoModelForZeroShotObjectDetection.from_pretrained(
        paths["dino"], local_files_only=True
    ).eval().to("cuda")
    sam_processor = Sam2Processor.from_pretrained(paths["sam2"], local_files_only=True)
    model = Sam2Model.from_pretrained(paths["sam2"], local_files_only=True).eval().to("cuda")

    def run(image, prompts, threshold, text_threshold):
        rows = []
        # ラベルごとに検出することで自由文のtokenとtaxonomyの曖昧な対応を避ける。
        for label, prompt in sorted(prompts.items()):
            inputs = processor(images=image, text=prompt + ".", return_tensors="pt").to("cuda")
            detections = processor.post_process_grounded_object_detection(
                detector(**inputs), inputs.input_ids, threshold=threshold,
                text_threshold=text_threshold, target_sizes=[(image.height, image.width)],
            )[0]
            # 12GB GPUで検出数に比例したピークを避けるため、boxは1件ずつ処理する。
            for box, score in zip(detections["boxes"], detections["scores"], strict=True):
                sam_inputs = sam_processor(
                    images=image, input_boxes=[[box.cpu().tolist()]], return_tensors="pt"
                ).to("cuda")
                output = model(**sam_inputs, multimask_output=False)
                mask = sam_processor.post_process_masks(
                    output.pred_masks.cpu(), sam_inputs["original_sizes"].cpu()
                )[0][0, 0].numpy().astype(np.bool_)
                rows.append((label, mask, float(score)))
        return rows

    return run
