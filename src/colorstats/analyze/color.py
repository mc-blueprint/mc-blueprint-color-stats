"""画像全体の観測色を抽出するcolor stage。"""

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from sqlalchemy.orm import Session

from colorstats.colors import QUANTILES, rgb_to_oklab
from colorstats.queue.core import Claim, RunInfo
from colorstats.queue.worker import Prepared
from colorstats.schema.models import ColorObservation, ProcessingRunInput

CLUSTERS = 5
SEED = 0
BLACK_MAX = 5
WHITE_MIN = 250


def extract_colors(
    image: Image.Image, mask: np.ndarray | None = None, *, clusters: int = CLUSTERS
) -> list[dict]:
    """有効画素をOKLabで分類し、主色・分位点・有効面積に対する比を返す。

    maskは画像と同寸の2次元bool配列。未指定なら画像全体を対象とする。
    不透明画素のうち全RGB成分が5以下または250以上の画素は除外する。
    有効画素なし、不正なmask、正整数でないclustersはValueError。
    入力画像は変更しない。結果は面積の降順、同面積は主色の辞書順とする。
    """
    if not isinstance(clusters, int) or isinstance(clusters, bool) or clusters < 1:
        raise ValueError("clustersは正整数で指定してください")
    rgba = np.asarray(image.convert("RGBA"))
    rgb = rgba[:, :, :3]
    valid = (
        (rgba[:, :, 3] == 255)
        & ~np.all(rgb <= BLACK_MAX, axis=2)
        & ~np.all(rgb >= WHITE_MIN, axis=2)
    )
    if mask is not None:
        if mask.shape != valid.shape or mask.dtype != np.bool_:
            raise ValueError("maskは画像と同寸の2次元bool配列で指定してください")
        valid &= mask
    selected = rgb[valid]
    if not len(selected):
        raise ValueError("色を抽出できる有効画素がありません")
    pixels = rgb_to_oklab(selected.astype(np.float64) / 255)
    count = min(clusters, len(np.unique(selected, axis=0)))
    cv2.setRNGSeed(SEED)
    _, labels, _ = cv2.kmeans(
        pixels.astype(np.float32).reshape(-1, 1, 3),
        count,
        None,
        (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-6),
        1,
        cv2.KMEANS_PP_CENTERS,
    )
    records = []
    for label in range(count):
        members = pixels[labels.ravel() == label]
        records.append({
            "observed_oklab": {
                "dominant": members.mean(axis=0).tolist(),
                "quantiles": [
                    {"q": q, "value": np.quantile(members, q, axis=0).tolist()}
                    for q in QUANTILES
                ],
            },
            "area_ratio": len(members) / len(pixels),
        })
    return sorted(
        records, key=lambda row: (-row["area_ratio"], row["observed_oklab"]["dominant"])
    )


def prepare(claim: Claim) -> Prepared:
    """payloadのinput_pathと任意のmask_pathを読み、試行固有のJSONを生成する。

    output_path、license_class、taxonomy_versionは必須。mask画像は非ゼロを採用する。
    prep由来では確定済みの不変input_pathとinput_run_idを呼出し側で指定する。
    assetを持たないclaimはValueError。画像やパスの読込み例外はそのまま送出する。
    """
    if claim.asset_id is None:
        raise ValueError("color stageにはasset_idが必要です")
    mask = None
    if claim.payload.get("mask_path"):
        with Image.open(claim.payload["mask_path"]) as source:
            mask = np.asarray(source.convert("L")) != 0
    with Image.open(claim.payload["input_path"]) as image:
        records = extract_colors(image, mask)
    target = Path(claim.payload["output_path"])
    temporary = target.with_name(f".{target.name}.{claim.token}.tmp")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "asset_id": str(claim.asset_id),
        "input_run_id": claim.payload.get("input_run_id"),
        "observations": records,
    }
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return Prepared(
        RunInfo(
            license_class=claim.payload["license_class"],
            code_version="issue-12",
            taxonomy_version=claim.payload["taxonomy_version"],
            node="color",
            parameters={
                "clusters": CLUSTERS,
                "seed": SEED,
                "black_max": BLACK_MAX,
                "white_min": WHITE_MIN,
                "alpha": 255,
                "quantiles": list(QUANTILES),
                "attempts": 1,
                "max_iter": 100,
                "epsilon": 1e-6,
                "input_path": claim.payload["input_path"],
                "mask_path": claim.payload.get("mask_path"),
                "opencv_version": cv2.__version__,
            },
        ),
        data=data,
        files=[(temporary, target)],
    )


def register(session: Session, run, data: dict) -> None:
    """画像全体の観測と入力runの由来を登録する。取引はキューが管理する。"""
    session.add_all(
        ColorObservation(asset_id=data["asset_id"], processing_run_id=run.id, **row)
        for row in data["observations"]
    )
    if data["input_run_id"] is not None:
        session.add(ProcessingRunInput(run_id=run.id, input_run_id=data["input_run_id"]))
