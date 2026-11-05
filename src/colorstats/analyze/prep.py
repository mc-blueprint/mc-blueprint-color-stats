"""画像のprep stage。"""

import hashlib
from pathlib import Path

import imagehash
from PIL import Image, ImageFilter, ImageStat
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from colorstats.queue.core import Claim, RunInfo
from colorstats.queue.worker import Prepared
from colorstats.rights import combine_license
from colorstats.schema.models import Asset, AssetDuplicate, Source, SubjectCandidate
from colorstats.store import temporary_path

MAX_SIZE = (512, 512)
PHASH_DISTANCE = 6
MIN_DIMENSION = 256
MIN_SHARPNESS = 100.0


def _inspect(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)

    with Image.open(path) as source:
        image = source.convert("RGB")
        width, height = image.size
        phash = str(imagehash.phash(image))
        edges = image.filter(ImageFilter.FIND_EDGES)
        sharpness = ImageStat.Stat(edges).var[0]
        gray = image.convert("L")
        corner = max(
            ImageStat.Stat(gray.crop(box)).stddev[0]
            for box in (
                (0, 0, width // 5, height // 5),
                (width * 4 // 5, 0, width, height // 5),
                (0, height * 4 // 5, width // 5, height),
                (width * 4 // 5, height * 4 // 5, width, height),
            )
        )
        luminance = ImageStat.Stat(gray).mean[0]
        color_count = image.getcolors(maxcolors=257)
        colors = 257 if color_count is None else len(color_count)
        resized = image.copy()
        resized.thumbnail(MAX_SIZE, Image.Resampling.LANCZOS)
        return {
            "sha256": digest.hexdigest(),
            "phash": phash,
            "width": width,
            "height": height,
            "sharpness": round(sharpness, 3),
            "watermark_suspected": corner > 70,
            "collage_suspected": colors > 256 and width / height > 1.4,
            "colors": colors,
            "luminance": luminance,
            "resized": resized,
        }


def prepare(claim: Claim) -> Prepared:
    """payloadの画像を解析し、縮小画像を一時ファイルへ書き出す。"""
    source = Path(claim.payload["input_path"])
    target = Path(claim.payload["derived_path"])
    result = _inspect(source)
    image = result.pop("resized")
    temporary = temporary_path(target, str(claim.token))
    image.save(temporary, format="JPEG", quality=90, optimize=True)
    data = {"asset_id": str(claim.asset_id), "target": str(target), **result}
    return Prepared(
        RunInfo(
            license_class=claim.payload["license_class"],
            code_version="issue-10",
            taxonomy_version=claim.payload["taxonomy_version"],
            node="prep",
            parameters={
                "max_size": list(MAX_SIZE), "phash_distance": PHASH_DISTANCE,
                "rendition": claim.payload.get("rendition", {}),
                "transform": {"mode": "RGB", "resample": "LANCZOS", "format": "JPEG",
                              "quality": 90, "optimize": True},
            },
        ),
        data=data,
        files=[(temporary, target)],
    )


def _quality(data: dict) -> dict:
    domain_estimate = (
        "mc_vanilla"
        if data["colors"] <= 64 and data["luminance"] > 8
        else "mc_modded_or_shader"
        if data["luminance"] > 180 and data["sharpness"] > 100
        else "mc_unknown"
    )
    return {
        "resolution_ok": min(data["width"], data["height"]) >= MIN_DIMENSION,
        "sharpness": data["sharpness"],
        "blur_suspected": data["sharpness"] < MIN_SHARPNESS,
        "watermark_suspected": data["watermark_suspected"],
        "collage_suspected": data["collage_suspected"],
        "domain_estimate": domain_estimate,
    }


def register(session: Session, run, data: dict) -> None:
    """同一取引で重複関係と候補を登録する。確定subjectは保持する。

    PostgreSQLのREAD COMMITTEDで呼び出す。完全一致群の確定subjectが一意の
    場合だけ未同定assetへ引き継ぎ、近似一致や確定値の競合では自動同定しない。
    """
    session.execute(text("SELECT pg_advisory_xact_lock(29, 1)"))
    assets = session.scalars(
        select(Asset).order_by(Asset.id).with_for_update().execution_options(populate_existing=True)
    ).all()
    asset = session.get(Asset, data["asset_id"])
    if run is not None:
        run.parameters = {**run.parameters, "rendition": asset.quality.get("rendition", {})}
        source = session.get(Source, asset.source_id)
        run.license_class = combine_license(
            run.license_class, asset.license_class, source.license_class
        )
    asset.sha256 = data["sha256"]
    asset.phash = data["phash"]
    asset.width = data["width"]
    asset.height = data["height"]
    asset.quality = {**asset.quality, **_quality(data)}

    candidates = []
    for other in assets:
        if other.id == asset.id:
            continue
        if other.sha256 == asset.sha256:
            candidates.append((other, 1.0, "sha256"))
        elif other.phash:
            distance = imagehash.hex_to_hash(asset.phash) - imagehash.hex_to_hash(other.phash)
            if distance <= PHASH_DISTANCE:
                candidates.append((other, 1 - distance / 64, "phash"))

    exact = [asset] + [other for other, _, method in candidates if method == "sha256"]
    subject_ids = {item.subject_id for item in exact if item.subject_id is not None}
    if len(subject_ids) == 1:
        subject_id = next(iter(subject_ids))
        for item in exact:
            if item.subject_id is None:
                item.subject_id = subject_id
    for other, confidence, method in candidates:
        first, second = sorted((asset.id, other.id))
        session.merge(
            AssetDuplicate(
                asset_a=first,
                asset_b=second,
                method=method,
                confidence=confidence,
            )
        )
        for target, origin in ((asset, other), (other, asset)):
            if origin.subject_id is not None:
                previous = session.get(SubjectCandidate, (target.id, origin.subject_id))
                if (
                    previous is None
                    or confidence > previous.confidence
                    or (
                        confidence == previous.confidence
                        and method == "sha256"
                        and previous.evidence.get("method") == "phash"
                    )
                ):
                    session.merge(
                        SubjectCandidate(
                            asset_id=target.id,
                            subject_id=origin.subject_id,
                            confidence=confidence,
                            evidence={
                                "method": method,
                                "asset_id": str(origin.id),
                                "sha256": asset.sha256,
                                "phash": asset.phash,
                            },
                        )
                    )
