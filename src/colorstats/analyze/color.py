"""画像全体と部位の観測色・部位間の関係を抽出するcolor stage。"""

import hashlib
import json
import uuid
from itertools import combinations
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.orm import Session

from colorstats.analyze.segment import _license
from colorstats.colors import QUANTILES, rgb_to_oklab
from colorstats.queue.core import Claim, RunInfo
from colorstats.queue.worker import Prepared
from colorstats.retention import check_privacy
from colorstats.schema.models import (
    Asset,
    ColorObservation,
    Job,
    ProcessingRun,
    ProcessingRunInput,
    Region,
    Relation,
)
from colorstats.store import temporary_path

CLUSTERS = 5
SEED = 0
BLACK_MAX = 5
WHITE_MIN = 250
ACHROMATIC_CHROMA = 2e-4
CODE_VERSION = "issue-45-v1"


def config_hash(payload: dict) -> str:
    """コード版・payload・入力画像と全マスクの内容から投入用SHA-256を返す。

    region_run_idとregionsは組で指定する。regionsはregion_inputsの戻り値を使い、
    投入後は画像・マスクを変更しない。読取り失敗は呼出し元へ伝播する。
    """
    if payload.get("region_policy") is not None:
        from colorstats.analyze.region_policy import load_masks

        load_masks(payload)
    paths = [payload["input_path"]]
    if payload.get("mask_path"):
        paths.append(payload["mask_path"])
    if payload.get("person_mask"):
        paths.append(payload["person_mask"])
    paths.extend(row["mask_path"] for row in payload.get("regions", []))
    hashes = {}
    for path in paths:
        with Path(path).open("rb") as stream:
            hashes[path] = hashlib.file_digest(stream, "sha256").hexdigest()
    if payload.get("input_sha256", hashes[payload["input_path"]]) != hashes[payload["input_path"]]:
        raise ValueError("入力画像のSHA-256が固定入力と一致しません")
    return hashlib.sha256(json.dumps(
        {"code_version": CODE_VERSION, "payload": payload, "files": hashes},
        sort_keys=True, ensure_ascii=False, allow_nan=False,
    ).encode()).hexdigest()


def region_inputs(session: Session, asset_id, region_run_id) -> list[dict]:
    """成功済みsegment・人手runの領域をpayload用の不変参照へ解決する。

    同じasset・taxonomyの領域だけをID順で返す。人手polygonは原画像寸法、
    modelのPNGはsegment画像寸法を持つ。不正な由来・未確定runはValueError。
    ファイルI/Oと取引の確定は行わない。空の検出結果も受け付ける。
    """
    asset = session.get(Asset, asset_id)
    source = session.get(ProcessingRun, region_run_id)
    if (asset is None or source is None or source.finished_at is None
            or source.failure_reason is not None
            or source.taxonomy_version != asset.taxonomy_version
            or source.stage not in {"segment", "human_annotation"}):
        raise ValueError("region_run_idには成功済みの同じtaxonomyの部位runが必要です")
    if source.stage == "segment":
        job = session.scalar(select(Job).where(
            Job.run_id == source.id, Job.asset_id == asset.id,
            Job.stage == "segment", Job.status == "succeeded",
        ))
        if job is None:
            raise ValueError("segment runのassetまたは成功状態が一致しません")
        size = [source.parameters["metrics"][key] for key in ("width", "height")]
        kind = "model"
    else:
        if session.scalar(select(Region.id).where(
            Region.processing_run_id == source.id, Region.asset_id == asset.id,
        ).limit(1)) is None:
            raise ValueError("人手runに対象assetの領域がありません")
        size = [asset.width, asset.height]
        kind = "human"
    records = []
    for region in session.scalars(select(Region).where(
        Region.asset_id == asset.id, Region.processing_run_id == source.id,
    ).order_by(Region.id)):
        if (region.label_source != kind or region.taxonomy_version != asset.taxonomy_version
                or region.mask_path is None):
            raise ValueError("領域の由来・taxonomy・mask_pathが不正です")
        if kind == "model":
            if region.mask_path not in source.output_paths.values():
                raise ValueError("領域マスクがsegmentの不変出力ではありません")
            path = region.mask_path
        else:
            path = str(Path(source.output_paths["masks"]) / region.mask_path)
        records.append({
            "region_id": str(region.id), "mask_path": path, "label_source": kind,
            "size": size,
        })
    return records


def region_policy_input(session: Session, asset_id, region_run_id):
    """同一assetの成功segmentから共有payload用region_policyを解決する。旧runはNone。

    region_inputsと併用し、新policyは省略せずpayloadへ渡す。DB変更は行わない。
    """
    from colorstats.analyze.region_policy import reference

    region_inputs(session, asset_id, region_run_id)
    return reference(session.get(ProcessingRun, region_run_id))


def role_observations(payload, *, corrected=None):
    """有効role maskから直接色を計算する。空roleは観測なし・欠測として返す。

    correctedがある場合は同じ画素の推定材質色を併記する。子Regionをsupportedへ昇格しない。
    """
    from colorstats.analyze.region_policy import load_masks
    from colorstats.analyze.shade import _summary

    masks = load_masks(payload)
    records = {}
    with Image.open(payload["input_path"]) as image:
        rgba = np.asarray(image.convert("RGBA"))
        rgb = rgba[:, :, :3]
        valid = ((rgba[:, :, 3] == 255) & ~np.all(rgb <= BLACK_MAX, axis=2)
                 & ~np.all(rgb >= WHITE_MIN, axis=2))
        if corrected is not None and (corrected.shape != rgb.shape
                                      or not np.isfinite(corrected).all()):
            raise ValueError("補正画像の寸法または画素が不正です")
        for role, mask in masks.items():
            selected = mask & valid
            observations = []
            if selected.any():
                observations = extract_colors(image, mask)
                if corrected is not None:
                    observations = [{
                        "observed_oklab": _summary(rgb_to_oklab(rgb[selected] / 255)),
                        "material_oklab": _summary(rgb_to_oklab(corrected[selected])),
                        "material_confidence": float(selected.sum() / mask.sum()),
                        "area_ratio": 1.0,
                    }]
            records[role] = {"area_ratio": float(mask.mean()), "area": int(mask.sum()),
                             "missing": not bool(selected.any()), "observations": observations}
    return records


def _region_mask(row, size):
    if row["label_source"] == "human":
        data = json.loads(Path(row["mask_path"]).read_text(encoding="utf-8"))
        if data["format"] != "polygon-pixels-v1":
            raise ValueError("未対応の部位マスク形式です")
        mask = Image.new("L", size)
        points = [(x * size[0] / row["size"][0], y * size[1] / row["size"][1])
                  for x, y in data["points"]]
        ImageDraw.Draw(mask).polygon(points, fill=255)
    else:
        with Image.open(row["mask_path"]) as image:
            if list(image.size) != row["size"]:
                raise ValueError("segmentマスクの寸法が由来と一致しません")
            mask = image.convert("L").resize(size, Image.Resampling.NEAREST)
    return np.asarray(mask) != 0


def extract_relations(regions: list[dict]) -> list[dict]:
    """ID順の部位主色から共起関係を返す。差はB−A、面積比はB/A。

    各部位のobservationsはextract_colorsの面積順、areaはマスク画素数。
    Δhは度の最短符号付き差で、彩度が2e-4以下なら未定義（None）。
    """
    records = []
    for a, b in combinations(regions, 2):
        ca, cb = (np.asarray(row["observations"][0]["observed_oklab"]["dominant"])
                  for row in (a, b))
        chroma_a, chroma_b = (float(np.hypot(color[1], color[2])) for color in (ca, cb))
        hue_a, hue_b = (float(np.degrees(np.arctan2(color[2], color[1])))
                        for color in (ca, cb))
        records.append({
            "region_a": a["region_id"], "region_b": b["region_id"], "type": "co_occurs",
            "delta_l": float(cb[0] - ca[0]), "delta_c": chroma_b - chroma_a,
            "delta_h": (hue_b - hue_a + 180) % 360 - 180
            if min(chroma_a, chroma_b) > ACHROMATIC_CHROMA else None,
            "delta_e_ok": float(np.linalg.norm(cb - ca)), "area_ratio": b["area"] / a["area"],
        })
    return records


def extract_colors(
    image: Image.Image, mask: np.ndarray | None = None, *, clusters: int = CLUSTERS,
    clip_extremes: bool = True,
) -> list[dict]:
    """有効画素をOKLabで分類し、主色・分位点・有効面積に対する比を返す。

    maskは画像と同寸の2次元bool配列。未指定なら画像全体を対象とする。
    不透明画素のうち全RGB成分が5以下または250以上の画素は除外する。
    clip_extremes=Falseは黒白も含めた面積で分類する。
    有効画素なし、不正なmask、正整数でないclustersはValueError。
    入力画像は変更しない。結果は面積の降順、同面積は主色の辞書順とする。
    """
    if not isinstance(clusters, int) or isinstance(clusters, bool) or clusters < 1:
        raise ValueError("clustersは正整数で指定してください")
    rgba = np.asarray(image.convert("RGBA"))
    rgb = rgba[:, :, :3]
    valid = rgba[:, :, 3] == 255
    if clip_extremes:
        valid &= ~np.all(rgb <= BLACK_MAX, axis=2) & ~np.all(rgb >= WHITE_MIN, axis=2)
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
    if claim.payload.get("region_policy") is not None:
        if config_hash(claim.payload) != claim.config_hash:
            raise ValueError("colorの設定ハッシュが一致しません")
        roles = role_observations(claim.payload)
        target = Path(claim.payload["output_path"])
        temporary = temporary_path(target, str(claim.token))
        data = {"asset_id": str(claim.asset_id),
                "input_run_id": claim.payload["input_run_id"],
                "region_run_id": claim.payload["region_run_id"],
                "observations": [], "regions": [], "relations": [], "roles": roles}
        temporary.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False) + "\n",
                             encoding="utf-8")
        return Prepared(RunInfo(
            license_class=claim.payload["license_class"], code_version=CODE_VERSION,
            taxonomy_version=claim.payload["taxonomy_version"], node="color",
            parameters={"payload": claim.payload, "region_policy": claim.payload["region_policy"]},
        ), data=data, files=[(temporary, target)])
    rows = claim.payload.get("regions", [])
    if ("regions" in claim.payload) != (claim.payload.get("region_run_id") is not None):
        raise ValueError("regionsとregion_run_idは組で指定してください")
    if claim.payload.get("region_run_id") and config_hash(claim.payload) != claim.config_hash:
        raise ValueError("colorの設定ハッシュが一致しません")
    ids = [row["region_id"] for row in rows]
    if ids != sorted(set(ids)):
        raise ValueError("regionsは重複のないID順で指定してください")
    mask = None
    if claim.payload.get("mask_path"):
        with Image.open(claim.payload["mask_path"]) as source:
            mask = np.asarray(source.convert("L")) != 0
    with Image.open(claim.payload["input_path"]) as image:
        if claim.payload.get("person_mask"):
            with Image.open(claim.payload["person_mask"]) as person:
                people = np.asarray(person.convert("L")) != 0
            if people.shape != (image.height, image.width):
                raise ValueError("人物maskは解析画像と同寸で指定してください")
            mask = ~people if mask is None else mask & ~people
        records = extract_colors(image, mask)
        regions = []
        for row in rows:
            part_mask = _region_mask(row, image.size)
            area = int((part_mask & ~people).sum()) if claim.payload.get("person_mask") else int(
                part_mask.sum(),
            )
            if mask is not None:
                part_mask &= mask
            if not area and claim.payload.get("person_mask"):
                continue
            regions.append({
                "region_id": row["region_id"], "area": area,
                "observations": extract_colors(image, part_mask),
            })
    target = Path(claim.payload["output_path"])
    temporary = temporary_path(target, str(claim.token))
    data = {
        "asset_id": str(claim.asset_id),
        "input_run_id": claim.payload.get("input_run_id"),
        "observations": records,
        "region_run_id": claim.payload.get("region_run_id"),
        "regions": regions,
        "relations": extract_relations(regions),
    }
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return Prepared(
        RunInfo(
            license_class=claim.payload["license_class"],
            code_version=CODE_VERSION,
            taxonomy_version=claim.payload["taxonomy_version"],
            node="color",
            parameters={
                "clusters": CLUSTERS,
                "seed": SEED,
                "black_max": BLACK_MAX,
                "white_min": WHITE_MIN,
                "achromatic_chroma": ACHROMATIC_CHROMA,
                "alpha": 255,
                "quantiles": list(QUANTILES),
                "attempts": 1,
                "max_iter": 100,
                "epsilon": 1e-6,
                "input_path": claim.payload["input_path"],
                "mask_path": claim.payload.get("mask_path"),
                "opencv_version": cv2.__version__,
                "payload": claim.payload,
            },
        ),
        data=data,
        files=[(temporary, target)],
    )


def register(session: Session, run, data: dict) -> None:
    """全体・部位観測と共起関係を、入力由来照合後に登録する。

    入力prepは同じassetの成功済みrunと不変出力に限る。領域スナップショットは
    DBの確定参照と一致する必要がある。不一致はValueErrorで取引を戻す。
    ファイルI/Oは行わず、取引・所有権はキューが管理する。
    """
    asset = session.get(Asset, data["asset_id"])
    payload = run.parameters["payload"]
    if asset is None or run.taxonomy_version != asset.taxonomy_version:
        raise ValueError("assetまたはtaxonomyが一致しません")
    check_privacy(session, asset.id, payload)
    licenses = [run.license_class, asset.license_class]
    inputs = set()
    if payload.get("privacy_review_run_id"):
        inputs.add(uuid.UUID(payload["privacy_review_run_id"]))
    if data["input_run_id"] is not None:
        previous = session.get(ProcessingRun, data["input_run_id"])
        job = session.scalar(select(Job).where(
            Job.run_id == data["input_run_id"], Job.asset_id == asset.id,
            Job.stage == "prep", Job.status == "succeeded",
        ))
        if (previous is None or previous.stage != "prep" or job is None
                or previous.finished_at is None or previous.failure_reason is not None
                or payload["input_path"] not in previous.output_paths.values()):
            raise ValueError("input_run_idは同じassetの成功済みprepと不変出力が必要です")
        licenses.append(previous.license_class)
        inputs.add(previous.id)
    if data["region_run_id"] is not None:
        expected = region_inputs(session, asset.id, data["region_run_id"])
        if expected != payload["regions"]:
            raise ValueError("部位入力がDBの確定参照と一致しません")
        source = session.get(ProcessingRun, data["region_run_id"])
        from colorstats.analyze.region_policy import reference

        expected_policy = reference(source)
        if expected_policy != payload.get("region_policy"):
            raise ValueError("region-policyがsegment runの確定参照と一致しません")
        if expected_policy is not None and (
            data["observations"] or data["regions"] or data["relations"] or "roles" not in data
        ):
            raise ValueError("新policyで旧観測・子Region観測は再利用できません")
        if source.stage == "segment":
            if (payload.get("input_sha256") is not None
                    and source.parameters.get("input_sha256") != payload["input_sha256"]):
                raise ValueError("segmentとcolorの入力画像hashが一致しません")
            if source.parameters["payload"]["input_path"] != payload["input_path"]:
                raise ValueError("segmentとcolorの入力画像が一致しません")
            if source.parameters["payload"].get("input_run_id") != data["input_run_id"]:
                raise ValueError("segmentとcolorの入力prepが一致しません")
        if data["input_run_id"] is None and payload["input_path"] != asset.storage_path:
            raise ValueError("原画像入力はasset.storage_pathと一致する必要があります")
        inputs.add(source.id)
        licenses.append(source.license_class)
    run.license_class = _license(*licenses)
    session.add_all(
        ColorObservation(asset_id=data["asset_id"], processing_run_id=run.id, **row)
        for row in data["observations"]
    )
    for region in data["regions"]:
        session.add_all(ColorObservation(
            region_id=region["region_id"], processing_run_id=run.id, **row,
        ) for row in region["observations"])
    session.add_all(Relation(
        asset_id=asset.id, processing_run_id=run.id, **row,
    ) for row in data["relations"])
    session.add_all(ProcessingRunInput(run_id=run.id, input_run_id=input_id) for input_id in inputs)
