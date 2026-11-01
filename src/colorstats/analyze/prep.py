"""画像のprep stage。"""

import hashlib
from pathlib import Path

import imagehash
from PIL import Image, ImageFilter, ImageStat
from sqlalchemy import select
from sqlalchemy.orm import Session

from colorstats.queue.core import Claim, RunInfo
from colorstats.queue.worker import Prepared
from colorstats.schema.models import Asset, Subject, SubjectCandidate

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
    temporary = target.with_name(f".{target.name}.{claim.token}.tmp")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    image.save(temporary, format="JPEG", quality=90, optimize=True)
    data = {"asset_id": str(claim.asset_id), "target": str(target), **result}
    return Prepared(
        RunInfo(
            license_class=claim.payload["license_class"],
            code_version="issue-10",
            taxonomy_version=claim.payload["taxonomy_version"],
            node="prep",
            parameters={"max_size": list(MAX_SIZE), "phash_distance": PHASH_DISTANCE},
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
    asset = session.get(Asset, data["asset_id"])
    asset.sha256 = data["sha256"]
    asset.phash = data["phash"]
    asset.width = data["width"]
    asset.height = data["height"]
    asset.quality = {**asset.quality, **_quality(data)}

    candidates = []
    for other in session.scalars(select(Asset).where(Asset.id != asset.id)):
        if other.sha256 == asset.sha256:
            candidates.append((other, 1.0, "sha256"))
        elif other.phash:
            distance = imagehash.hex_to_hash(asset.phash) - imagehash.hex_to_hash(other.phash)
            if distance <= PHASH_DISTANCE:
                candidates.append((other, 1 - distance / 64, "phash"))

    subject_ids = {other.subject_id for other, _, _ in candidates if other.subject_id}
    if not subject_ids:
        subject = Subject(
            name=asset.collected_title or asset.url,
            domain=asset.domain,
            taxonomy_version=asset.taxonomy_version,
            scene_attributes=asset.scene_attributes or {},
        )
        session.add(subject)
        session.flush()
        subject_ids.add(subject.id)
    asset.subject_id = sorted(subject_ids, key=str)[0]
    for other, confidence, method in candidates:
        subject_id = other.subject_id or asset.subject_id
        if other.subject_id is None:
            other.subject_id = subject_id
        session.merge(
            SubjectCandidate(
                asset_id=asset.id,
                subject_id=subject_id,
                confidence=confidence,
                evidence={"method": method, "sha256": asset.sha256, "phash": asset.phash},
            )
        )
