"""ローカルに配置済みの公式重みを使うGPU推論。重みの自動取得は行わない。"""

import json
import time
from functools import lru_cache
from pathlib import Path

import numpy as np

from colorstats.queue.core import NonRetryableError

REPOSITORIES = {
    "sam2": "facebook/sam2.1-hiera-tiny",
    "dino": "IDEA-Research/grounding-dino-tiny",
}


def _unload():
    import gc
    import sys

    import torch

    _resident.cache_clear()
    sam2 = sys.modules.get("transformers.models.sam2.modeling_sam2")
    if sam2 is not None:
        # 公式のcompile対応ラッパーにはcache_clearがないため、空のラッパーへ置換する。
        embedding = sam2.Sam2SinePositionEmbedding
        embedding.forward = sam2.compile_compatible_method_lru_cache(maxsize=1)(
            embedding.forward.__wrapped__,
        )
    gc.collect()
    torch.cuda.empty_cache()


def _oneformer_processor(path):
    from transformers import CLIPTokenizer, OneFormerImageProcessor, OneFormerProcessor

    config = json.loads((Path(path) / "preprocessor_config.json").read_text("utf-8"))
    parameters = {key: config[key] for key in (
        "do_resize", "size", "resample", "do_rescale", "rescale_factor", "do_normalize",
        "image_mean", "image_std", "ignore_index", "num_text", "num_labels",
    ) if key in config}
    image_processor = OneFormerImageProcessor(
        **parameters, repo_path=str(Path(__file__).parent),
        class_info_file="oneformer-classes.json", do_reduce_labels=False,
    )
    return OneFormerProcessor(
        image_processor=image_processor,
        tokenizer=CLIPTokenizer.from_pretrained(path, local_files_only=True),
    )


def _uncache_positions(model, embedding_type):
    # 公式LRUがGPU Tensorを保持するため、試行内の位置埋め込みはキャッシュしない。
    for module in model.modules():
        if isinstance(module, embedding_type):
            module.forward = module.forward.__wrapped__.__get__(module, type(module))


def predict_regions(image, payload, parameters):
    """OneFormerを解放してから既存DINO/SAM2候補を生成する。OOMは代替せず送出する。

    batch=1、processor短辺640/長辺2560を固定し、semantic logitsをprep寸法へ復元する。
    ローカル重みだけを使用する。モデル・processorの実行版と工程別VRAMを返す。
    """
    from importlib.metadata import version

    import torch

    from colorstats.analyze.region_policy import OOM_REASON, TRANSFORM, validate_labels

    if not torch.cuda.is_available():
        raise RuntimeError("OneFormer推論にはCUDAが必要です")
    versions = {name: version(name) for name in ("torch", "transformers", "Pillow")}
    if versions["transformers"] != "4.57.6" or versions["torch"].split("+")[0] != "2.11.0":
        raise RuntimeError("新policyはTransformers 4.57.6 / torch 2.11.0で実行してください")
    _unload()
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    model = processor = inputs = outputs = None
    try:
        from transformers import OneFormerForUniversalSegmentation
        from transformers.models.oneformer.modeling_oneformer import OneFormerSinePositionEmbedding

        path = payload["model_paths"]["oneformer"]
        processor = _oneformer_processor(path)
        processor.image_processor.size = {key: TRANSFORM[key]
                                          for key in ("shortest_edge", "longest_edge")}
        processor.image_processor._max_size = TRANSFORM["longest_edge"]
        model = OneFormerForUniversalSegmentation.from_pretrained(
            path, local_files_only=True, weights_only=True,
        ).eval().to("cuda")
        _uncache_positions(model, OneFormerSinePositionEmbedding)
        validate_labels({str(k): v for k, v in model.config.id2label.items()})
        torch.manual_seed(0)
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
            inputs = processor(
                images=image, task_inputs=["semantic"], return_tensors="pt",
            ).to("cuda")
            outputs = model(**inputs)
            semantic = processor.post_process_semantic_segmentation(
                outputs, target_sizes=[(image.height, image.width)],
            )[0].cpu().numpy().astype(np.uint8)
        torch.cuda.synchronize()
        metrics = {"oneformer_seconds": time.perf_counter() - started,
                   "oneformer_peak_allocated_bytes": torch.cuda.max_memory_allocated(),
                   "oneformer_peak_reserved_bytes": torch.cuda.max_memory_reserved()}
    except torch.cuda.OutOfMemoryError as error:
        raise NonRetryableError(OOM_REASON + ": OneFormerのGPU適合を確認してください") from error
    finally:
        del outputs, inputs, model, processor
        _unload()
    paths = {key: value for key, value in payload["model_paths"].items() if key != "oneformer"}
    hashes = {key: parameters["models"][key] for key in paths}
    from colorstats.analyze import visible_wall

    prompts = payload["prompts"]
    if payload.get("method") == visible_wall.METHOD:
        prompts = {**prompts, **visible_wall.EXTRA_PROMPTS}
    try:
        rows, candidate_metrics = predict(
            image, "sam2-dino", paths, hashes, prompts,
            parameters["threshold"], parameters["text_threshold"], transient=True,
        )
    except torch.cuda.OutOfMemoryError as error:
        raise NonRetryableError(OOM_REASON + ": 部位候補生成のGPU適合を確認してください") from error
    finally:
        _unload()
    metrics.update(candidate_metrics)
    metrics["versions"] = versions
    metrics["single_resident_phase"] = "oneformer-then-dino-sam2"
    return semantic, rows, metrics


def predict(image, method, paths, model_hashes, prompts, threshold, text_threshold, *,
            transient=False):
    """(label, boolマスク, confidence)の列とGPU計測を返す。CUDA必須。

    同じパス・実ファイルhashのモデルをプロセス内で保持する。初期化と推論を個別に計測し、VRAMは
    初期化も含むPyTorch allocatorの最大値。OOM・依存不足はそのまま送出する。
    transient=Trueは新policy用。モデル常駐と位置埋め込みLRUを使用しない。
    """
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("segmentの実モデル推論にはCUDAが必要です")
    torch.manual_seed(0)
    torch.cuda.reset_peak_memory_stats()
    start = time.perf_counter()
    if method != "sam2-dino":
        raise ValueError("methodはsam2-dinoです")
    files = tuple(
        (str(Path(paths[name]) / filename), digest)
        for name in sorted(paths)
        for filename, digest in sorted(model_hashes[name]["files"].items())
    )
    runner = (_sam2(dict(paths), cache_positions=False) if transient
              else _resident(tuple(sorted(paths.items())), files))
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


@lru_cache(maxsize=1)
def _resident(paths, files):
    return _sam2(dict(paths))


def _sam2(paths, *, cache_positions=True):
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
    if not cache_positions:
        from transformers.models.sam2.modeling_sam2 import Sam2SinePositionEmbedding

        _uncache_positions(model, Sam2SinePositionEmbedding)

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
