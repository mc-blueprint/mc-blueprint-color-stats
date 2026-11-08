"""部位ラベル付きマスクを生成するsegment stage。"""

import hashlib
import json
import math
import socket
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from colorstats.analyze.segment_models import REPOSITORIES, predict
from colorstats.queue.core import Claim, RunInfo
from colorstats.queue.worker import Prepared
from colorstats.rights import LICENSES
from colorstats.rights import combine_license as _license
from colorstats.schema.models import Asset, Job, ProcessingRun, ProcessingRunInput, Region
from colorstats.schema.taxonomy import load_taxonomy
from colorstats.store import temporary_path

CODE_VERSION = "issue-66-v1"


def _hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()


def _configuration(payload):
    from colorstats.analyze import region_policy, visible_wall

    method = payload["method"]
    components = {"sam2", "dino"}
    if method in (region_policy.METHOD, visible_wall.METHOD):
        components.add("oneformer")
        if not payload.get("input_run_id") or not payload.get("input_sha256"):
            raise ValueError("新segmentには固定prep runと入力SHAが必要です")
        with Image.open(payload["input_path"]) as image:
            if max(image.size) > 2560 or image.getexif().get(274, 1) != 1:
                raise ValueError("新segmentは長辺2560px以下・向き確定済みprepが必要です")
    elif method != "sam2-dino":
        raise ValueError("未対応のsegment methodです")
    if set(payload["model_paths"]) != components:
        raise ValueError("methodに必要なmodel_pathsを指定してください")
    taxonomy = load_taxonomy(Path(payload.get("taxonomy_path", "taxonomy")))
    if payload["taxonomy_version"] != taxonomy["parts"]["taxonomy_version"]:
        raise ValueError("taxonomy_versionが正本と一致しません")
    labels = {label for group in taxonomy["parts"]["groups"].values() for label in group}
    labels.update(taxonomy["terrain"]["labels"])
    prompts = payload["prompts"]
    if not prompts or set(prompts) - labels or any(
        not isinstance(prompt, str) or not prompt.strip() or "." in prompt
        for prompt in prompts.values()
    ):
        raise ValueError("promptsはtaxonomyの部位ラベルと空でない単一の英語句を指定してください")
    if payload["license_class"] not in LICENSES:
        raise ValueError("未知のlicense_classです")
    if Path(payload["output_path"]).suffix != ".json":
        raise ValueError("output_pathにはJSONの出力名を指定してください")
    threshold = payload.get("threshold", 0.35)
    text_threshold = payload.get("text_threshold", 0.25)
    if not (0 < threshold <= 1 and 0 < text_threshold <= 1):
        raise ValueError("thresholdとtext_thresholdは0より大きく1以下です")
    if method == visible_wall.METHOD and (threshold, text_threshold) != (0.35, 0.25):
        raise ValueError("可視壁材の候補閾値は0.35/0.25に固定してください")
    models = {}
    for name in sorted(components):
        path = Path(payload["model_paths"][name])
        if name == "oneformer":
            models[name] = region_policy.model_configuration(path)
            continue
        files = sorted(
            item for item in path.iterdir() if item.is_file() and item.suffix in {
                ".safetensors", ".json", ".txt", ".model"
            }
        )
        if not any(item.suffix == ".safetensors" for item in files):
            raise ValueError(f"{name}の公式safetensors重みがありません")
        models[name] = {
            "repository": REPOSITORIES[name],
            "license_class": "open",
            "files": {item.name: _hash(item) for item in files},
        }
    input_hash = _hash(payload["input_path"])
    if payload.get("input_sha256", input_hash) != input_hash:
        raise ValueError("入力画像のSHA-256が固定入力と一致しません")
    parameters = {
        "payload": payload, "models": models, "threshold": threshold,
        "text_threshold": text_threshold, "seed": 0, "precision": "bfloat16",
        "batch_size": 1, "box_batch_size": 1, "code_version": CODE_VERSION,
        "input_sha256": input_hash,
        "taxonomy_hash": _digest(taxonomy),
    }
    if method in (region_policy.METHOD, visible_wall.METHOD):
        parameters["region_policy_hash"] = (visible_wall.policy_hash()
                                            if method == visible_wall.METHOD
                                            else region_policy.policy_hash())
        parameters["parent_table"] = region_policy.parent_table_reference()
        parameters["transform"] = region_policy.TRANSFORM
    return parameters


def config_hash(payload: dict) -> str:
    """enqueue用の設定SHA-256。入力画像・実重み・processor設定・語彙を含む。

    payloadの契約はdocs/segment.md参照。ファイル読取りを伴い、未配置の重み、
    不正な手法・ラベル・版は例外にする。重みの取得やDB操作は行わない。
    """
    return _digest(_configuration(payload))


def _rle(mask):
    pixels = mask.ravel().astype(np.uint8)
    changes = np.flatnonzero(np.diff(pixels)) + 1
    lengths = np.diff(np.r_[0, changes, len(pixels)]).tolist()
    if pixels[0]:
        lengths.insert(0, 0)
    return ", ".join(map(str, lengths))


def prepare(claim: Claim) -> Prepared:
    """縮小画像からPNG・CVAT XML・計測JSONを試行専用パスへ生成する。

    CUDA推論は子プロセス内でモデルを再利用する。設定ハッシュ不一致、形状・信頼度の不正は
    ValueError。出力名は識別子で、確定パスはrun.output_pathsから解決する。
    未検出は空の成功結果とし、推論・I/O失敗はキューの再試行へ渡す。
    """
    started = time.perf_counter()
    if claim.asset_id is None:
        raise ValueError("segment stageにはasset_idが必要です")
    payload = claim.payload
    parameters = _configuration(payload)
    if _digest(parameters) != claim.config_hash:
        raise ValueError("segmentの設定ハッシュが一致しません。入力と重みを確認してください")
    with Image.open(payload["input_path"]) as source:
        image = source.convert("RGB")
    from colorstats.analyze import region_policy, visible_wall

    semantic = None
    exclusion_rows = []
    if payload["method"] in (region_policy.METHOD, visible_wall.METHOD):
        from colorstats.analyze.segment_models import predict_regions

        semantic, rows, metrics = predict_regions(image, payload, parameters)
        if payload["method"] == visible_wall.METHOD:
            exclusion_rows = [row for row in rows if row[0] in visible_wall.EXTRA_PROMPTS]
            rows = [row for row in rows if row[0] not in visible_wall.EXTRA_PROMPTS]
    else:
        rows, metrics = predict(
            image, payload["method"], payload["model_paths"], parameters["models"],
            payload["prompts"], parameters["threshold"], parameters["text_threshold"],
        )
    target = Path(payload["output_path"])
    files = []
    records = []
    annotations = ET.Element("annotations")
    ET.SubElement(annotations, "version").text = "1.1"
    task = ET.SubElement(ET.SubElement(annotations, "meta"), "task")
    ET.SubElement(task, "name").text = "segment"
    ET.SubElement(task, "size").text = "1"
    ET.SubElement(task, "mode").text = "annotation"
    labels = ET.SubElement(task, "labels")
    for label in sorted(payload["prompts"]):
        definition = ET.SubElement(labels, "label")
        ET.SubElement(definition, "name").text = label
        ET.SubElement(definition, "type").text = "mask"
        ET.SubElement(definition, "attributes")
    frame = ET.SubElement(annotations, "image", {
        "id": "0", "name": Path(payload["input_path"]).name,
        "width": str(image.width), "height": str(image.height),
    })
    mask_bytes = 0
    for label, mask, confidence in rows:
        if label not in payload["prompts"] or mask.dtype != np.bool_ or mask.shape != (
            image.height, image.width
        ) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("推論結果のラベル・マスク・信頼度が不正です")
        y, x = np.nonzero(mask)
        if not len(x):
            continue
        index = len(records)
        bbox = [int(x.min()), int(y.min()), int(x.max()) + 1, int(y.max()) + 1]
        mask_target = target.with_name(f"{target.stem}-{index:04d}.png")
        temporary = temporary_path(mask_target, str(claim.token))
        Image.fromarray(mask.astype(np.uint8) * 255).save(temporary, format="PNG")
        mask_bytes += temporary.stat().st_size
        files.append((temporary, mask_target))
        records.append({
            "label": label, "instance_id": str(index), "mask_path": str(mask_target),
            "bbox": bbox, "confidence": confidence, "area_ratio": len(x) / mask.size,
        })
        left, top, right, bottom = bbox
        ET.SubElement(frame, "mask", {
            "label": label, "source": "auto", "occluded": "0", "z_order": str(index),
            "left": str(left), "top": str(top), "width": str(right - left),
            "height": str(bottom - top), "rle": _rle(mask[top:bottom, left:right]),
        })
    xml_target = target.with_suffix(".xml")
    xml_temporary = temporary_path(xml_target, str(claim.token))
    ET.ElementTree(annotations).write(xml_temporary, encoding="utf-8", xml_declaration=True)
    files.append((xml_temporary, xml_target))
    policy = None
    if semantic is not None:
        if semantic.shape != (image.height, image.width):
            raise ValueError("semantic mapの復元寸法がprepと一致しません")
        policy, policy_files = region_policy.save_artifacts(
            target, str(claim.token), semantic, rows, payload["prompts"], parameters,
            exclusion_rows=exclusion_rows,
        )
        files.extend(policy_files)
        parameters["region_policy"] = policy
    metrics.update({
        "mask_bytes": mask_bytes, "cvat_bytes": xml_temporary.stat().st_size,
        "prepare_seconds": time.perf_counter() - started,
        "width": image.width, "height": image.height, "regions": len(records),
    })
    data = {
        "asset_id": str(claim.asset_id), "input_run_id": payload.get("input_run_id"),
        "regions": records, "metrics": metrics,
    }
    if policy is not None:
        data["region_policy"] = policy
    temporary = temporary_path(target, str(claim.token))
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    files.append((temporary, target))
    return Prepared(
        RunInfo(
            license_class=_license(payload["license_class"], *(
                model["license_class"] for model in parameters["models"].values()
            )),
            code_version=CODE_VERSION, taxonomy_version=payload["taxonomy_version"],
            node=socket.gethostname(), model_name=payload["method"],
            weights_hash=_digest({
                name: {key: value for key, value in model["files"].items()
                       if key.endswith((".safetensors", ".bin"))}
                for name, model in parameters["models"].items()
            }), parameters={**parameters, "metrics": metrics},
        ), data=data, files=files,
    )


def register(session: Session, run, data: dict) -> None:
    """所有権付き完了取引でRegion・入力runを登録し、ライセンス制約を伝播する。

    入力runは同じassetの成功済みprepとその不変出力に限り、不一致はValueError。
    """
    asset = session.get(Asset, data["asset_id"])
    licenses = [run.license_class, asset.license_class]
    if data["input_run_id"] is not None:
        previous = session.get(ProcessingRun, data["input_run_id"])
        payload = run.parameters["payload"]
        source_job = session.scalar(select(Job).where(
            Job.run_id == data["input_run_id"], Job.asset_id == asset.id,
            Job.stage == "prep", Job.status == "succeeded",
        ))
        if (
            previous is None or previous.stage != "prep" or source_job is None
            or previous.finished_at is None or previous.failure_reason is not None
            or payload["input_path"] not in previous.output_paths.values()
        ):
            raise ValueError(
                "input_run_idは同じassetの成功済みprepとその不変出力を指定してください"
            )
        licenses.append(previous.license_class)
        session.add(ProcessingRunInput(run_id=run.id, input_run_id=previous.id))
    run.license_class = _license(*licenses)
    session.add_all(Region(
        asset_id=asset.id, processing_run_id=run.id, taxonomy_version=run.taxonomy_version,
        normalized_height=None,
        label_source="model", **{**row, "mask_path": run.output_paths[row["mask_path"]]},
    ) for row in data["regions"])
