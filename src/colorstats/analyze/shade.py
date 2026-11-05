"""同一の部位マスクで陰影補正を比較するshade stage。"""

import json
import socket
from functools import lru_cache
from importlib.metadata import version
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import patch

import colour
import numpy as np
from PIL import Image
from sqlalchemy.orm import Session

from colorstats.analyze import color
from colorstats.analyze.segment import _digest, _hash, _license
from colorstats.colors import QUANTILES, rgb_to_oklab
from colorstats.queue.core import Claim, RunInfo
from colorstats.queue.worker import Prepared
from colorstats.rights import LICENSES
from colorstats.schema.models import Asset
from colorstats.store import temporary_path

CODE_VERSION = "issue-46-v4"
METHODS = ("none", "gray-world", "intrinsic")
INTRINSIC_REVISION = "1a93aafaaf7dbe11be7ec86323d9a06e5950966d"


def _configuration(payload):
    if payload["method"] not in METHODS:
        raise ValueError("methodはnone・gray-world・intrinsicです")
    if not payload.get("region_run_id") or "regions" not in payload:
        raise ValueError("shadeにはregion_run_idとregionsが必要です")
    if payload["license_class"] not in LICENSES:
        raise ValueError("未知のlicense_classです")
    parameters = {"payload": payload, "code_version": CODE_VERSION,
                  "input_hash": color.config_hash(payload)}
    if payload["method"] == "intrinsic":
        if payload.get("evaluation_only") is not True:
            raise ValueError("Intrinsicは評価専用です")
        root = Path(payload["model_path"])
        parameters["model"] = {
            "repository": "https://github.com/compphoto/Intrinsic",
            "revision": INTRINSIC_REVISION, "license_class": "academic_only",
            "weights": {f"stage_{i}.pt": _hash(root / f"stage_{i}.pt") for i in range(4)},
            "implementation": _implementation(),
        }
    return parameters


def _implementation():
    packages = {}
    for name in ("intrinsic", "altered_midas", "chrislib", "geffnet"):
        spec = find_spec(name)
        if spec is None:
            raise ValueError(f"評価用パッケージ{name}がありません")
        root = Path(spec.origin).parent
        packages[name] = {str(path.relative_to(root)): _hash(path)
                          for path in sorted(root.rglob("*.py"))}
    return {"packages": packages, "versions": {
        name: version(name) for name in (
            "torch", "torchvision", "timm", "geffnet", "numpy", "scikit-image",
        )
    }}


def config_hash(payload: dict) -> str:
    """画像・全マスク・設定・Intrinsic実重みを照合する投入用SHA-256。

    payloadはdocs/shade.md参照。ファイル読取りを伴い、不正な手法・評価区分や
    未配置の入力・重みは例外にする。取得、DB操作、モデル初期化は行わない。
    """
    return _digest(_configuration(payload))


@lru_cache(maxsize=1)
def _models(path, weights_hash):
    from intrinsic.pipeline import load_models

    # 公式loaderが上書き前のbackboneまで取得するため、同じ構造だけをローカル生成する。
    with patch("torch.hub.load", _backbone):
        return load_models([str(Path(path) / f"stage_{i}.pt") for i in range(4)], stage=3)


def _backbone(repository, model, **kwargs):
    if (repository, model) == ("facebookresearch/WSL-Images", "resnext101_32x8d_wsl"):
        from torchvision.models import resnext101_32x8d

        return resnext101_32x8d(weights=None)
    if (repository, model) == ("rwightman/gen-efficientnet-pytorch", "tf_efficientnet_lite3"):
        import geffnet

        return geffnet.create_model(model, pretrained=False, exportable=kwargs["exportable"])
    raise ValueError("公式v2で想定していないbackboneです")


def correct(image: Image.Image, method: str, *, model_path=None, weights_hash=None) -> np.ndarray:
    """入力sRGBを補正して同寸の0〜1 sRGB配列を返す。入力は変更しない。

    Gray-Worldは不透明かつ非白飛び・非黒つぶれ画素の線形RGB平均を中立化する。
    Intrinsicは別途配置した公式v2重みをCUDAで使い、線形hr_albをsRGBに符号化する。
    モデル・CUDA・推論の失敗は伝播し、他手法への代替や重み取得は行わない。
    """
    rgb = np.asarray(image.convert("RGB"), dtype=np.float64) / 255
    if method == "none":
        return rgb
    if method == "gray-world":
        rgba = np.asarray(image.convert("RGBA"))
        valid = ((rgba[:, :, 3] == 255) & ~np.all(rgba[:, :, :3] <= color.BLACK_MAX, axis=2)
                 & ~np.all(rgba[:, :, :3] >= color.WHITE_MIN, axis=2))
        if not valid.any():
            raise ValueError("WBを推定できる有効画素がありません")
        linear = colour.cctf_decoding(rgb, function="sRGB")
        means = linear[valid].mean(axis=0)
        if np.any(means == 0):
            raise ValueError("Gray-Worldのチャンネル平均が0です")
        return colour.cctf_encoding(np.clip(linear * (means.mean() / means), 0, 1),
                                    function="sRGB")
    if method != "intrinsic":
        raise ValueError("未知の補正手法です")
    import torch
    from intrinsic.pipeline import run_pipeline

    torch.manual_seed(0)
    deterministic = torch.are_deterministic_algorithms_enabled()
    warn_only = torch.is_deterministic_algorithms_warn_only_enabled()
    random_state = np.random.get_state()
    try:
        torch.use_deterministic_algorithms(True)
        with torch.backends.cudnn.flags(benchmark=False), torch.inference_mode():
            models = _models(model_path, weights_hash)
            np.random.seed(0)
            result = run_pipeline(models, rgb.astype(np.float32),
                                  stage=3, resize_conf=512)
    finally:
        np.random.set_state(random_state)
        torch.use_deterministic_algorithms(deterministic, warn_only=warn_only)
    albedo = result["hr_alb"]
    if albedo.ndim != 3 or albedo.shape[2] != 3 or not np.isfinite(albedo).all():
        raise ValueError("Intrinsicのalbedoが不正です")
    albedo = np.stack([
        np.asarray(Image.fromarray(albedo[:, :, i]).resize(image.size, Image.Resampling.BILINEAR))
        for i in range(3)
    ], axis=2)
    return colour.cctf_encoding(np.clip(albedo, 0, 1), function="sRGB")


def _summary(pixels):
    return {
        "dominant": pixels.mean(axis=0).tolist(),
        "quantiles": [{"q": q, "value": np.quantile(pixels, q, axis=0).tolist()}
                      for q in QUANTILES],
    }


def observations(image: Image.Image, corrected: np.ndarray, regions: list[dict],
                 *, person_mask=None) -> list[dict]:
    """各領域の同じ有効画素から観測色・推定色を集約する。

    1領域1観測でarea_ratio=1。confidenceは元マスクに対する有効画素率で、
    材質色が正しい確率ではない。有効画素なしの領域は結果を作らず欠測として扱う。
    person_maskの非ゼロ人物画素は集計と部位面積から除く。
    """
    rgba = np.asarray(image.convert("RGBA"))
    rgb = rgba[:, :, :3]
    if corrected.shape != rgb.shape or not np.isfinite(corrected).all():
        raise ValueError("補正画像の寸法または画素が不正です")
    valid = ((rgba[:, :, 3] == 255) & ~np.all(rgb <= color.BLACK_MAX, axis=2)
             & ~np.all(rgb >= color.WHITE_MIN, axis=2))
    records = []
    for row in regions:
        mask = color._region_mask(row, image.size)
        if person_mask is not None:
            mask &= ~person_mask
        selected = mask & valid
        if not selected.any():
            continue
        records.append({
            "region_id": row["region_id"], "area": int(mask.sum()),
            "observations": [{
                "observed_oklab": _summary(rgb_to_oklab(rgb[selected] / 255)),
                "material_oklab": _summary(rgb_to_oklab(corrected[selected])),
                "material_confidence": float(selected.sum() / mask.sum()), "area_ratio": 1.0,
            }],
        })
    return records


def prepare(claim: Claim) -> Prepared:
    """不変入力を照合し、補正結果を試行専用JSONへ保存する。DBは変更しない。"""
    if claim.asset_id is None:
        raise ValueError("shadeにはasset_idが必要です")
    payload = claim.payload
    parameters = _configuration(payload)
    if _digest(parameters) != claim.config_hash:
        raise ValueError("shadeの設定ハッシュが一致しません")
    ids = [row["region_id"] for row in payload["regions"]]
    if ids != sorted(set(ids)):
        raise ValueError("regionsは重複のないID順で指定してください")
    model = parameters.get("model")
    with Image.open(payload["input_path"]) as image:
        people = None
        if payload.get("person_mask"):
            with Image.open(payload["person_mask"]) as person:
                people = np.asarray(person.convert("L")) != 0
            if people.shape != (image.height, image.width):
                raise ValueError("人物maskは解析画像と同寸で指定してください")
            pixels = np.array(image.convert("RGBA"))
            pixels[people, 3] = 0
            image = Image.fromarray(pixels)
        corrected = correct(image, payload["method"], model_path=payload.get("model_path"),
                            weights_hash=_digest(model) if model else None)
        regions = observations(image, corrected, payload["regions"], person_mask=people)
    data = {
        "asset_id": str(claim.asset_id), "input_run_id": payload.get("input_run_id"),
        "region_run_id": payload["region_run_id"], "regions": regions,
        "observations": [], "relations": [],
    }
    target = Path(payload["output_path"])
    temporary = temporary_path(target, str(claim.token))
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                         encoding="utf-8")
    return Prepared(RunInfo(
        license_class=_license(payload["license_class"], "academic_only" if model else "open"),
        code_version=CODE_VERSION, taxonomy_version=payload["taxonomy_version"],
        node=socket.gethostname(), model_name=payload["method"],
        weights_hash=_digest(model["weights"]) if model else None, parameters=parameters,
    ), data=data, files=[(temporary, target)])


def register(session: Session, run, data: dict) -> None:
    """colorと同じ入力由来照合で新しい観測を登録する。既存観測を変更しない。"""
    payload = run.parameters["payload"]
    asset = session.get(Asset, data["asset_id"])
    if asset is None:
        raise ValueError("assetがありません")
    if data["input_run_id"] is None and payload["input_path"] != asset.storage_path:
        raise ValueError("原画像入力はasset.storage_pathと一致する必要があります")
    if payload["method"] == "intrinsic":
        if payload.get("evaluation_only") is not True:
            raise ValueError("Intrinsicは評価専用です")
        run.license_class = _license(run.license_class, "academic_only")
    color.register(session, run, data)
