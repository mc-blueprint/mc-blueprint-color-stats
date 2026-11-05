"""縮小収集の原本再判定jobと、対応比較の許容差監査。"""

import hashlib
import json
import logging
import math
import os
from pathlib import Path
from statistics import mean

from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert

from colorstats.queue import Queue, RunInfo
from colorstats.queue.worker import Prepared
from colorstats.schema.models import Job, ProcessingRun
from colorstats.store import temporary_path

QUALITY_POLICY = {
    "min_long_edge": 1280,
    "dominant_oklab_mean_max": 0.02,
    "major_agreement_min": 0.85,
    "original_review_flags": ["watermark_suspected", "blur_suspected", "collage_suspected"],
}
logger = logging.getLogger(__name__)


def schedule_original(session, run, asset, record, payload):
    """新規thumbnailのフラグだけを対象に、同じ登録取引で原本再判定を予約する。"""
    policy = payload.get("quality_policy")
    candidate = record["candidate"]
    if not policy or candidate.get("rendition", {}).get("variant") != "thumbnail":
        return
    reasons = [key for key in policy["original_review_flags"] if record["quality"][key]]
    if not reasons:
        return
    rendition = candidate["rendition"]
    original = {
        **candidate, "download_url": None,
        "rendition": {**rendition, "variant": "original"},
        "attribution": candidate["attribution"].replace(
            "API縮小・再圧縮の可能性あり", "原本・改変なし",
        ),
    }
    review = {
        **payload, "request": {**payload["request"], "download_mode": "original"},
        "original_review": {
            "asset_id": str(asset.id), "collect_run_id": str(run.id),
            "reasons": reasons, "from_variant": rendition, "candidate": original,
        },
    }
    digest = hashlib.sha256(json.dumps(review, sort_keys=True).encode()).hexdigest()
    job_id = session.scalar(insert(Job).values(
        stage="review", asset_id=asset.id, stage_config_hash=digest, payload=review,
    ).on_conflict_do_nothing(constraint="uq_job_key").returning(Job.id))
    run.parameters = {**run.parameters, "original_review_jobs": [
        *run.parameters.get("original_review_jobs", []),
        {"job_id": str(job_id), "asset_id": str(asset.id), "reasons": reasons,
         "from_variant": rendition},
    ]}


def audit(rows, policy=QUALITY_POLICY):
    """#90のcomparison行を集計する。未評価数を残し、欠測を合格とは扱わない。

    主色は組ごとの距離の平均、主要部位は全ラベルのintersection/unionの合算比。
    不正値はValueError。人手正解に対する精度とは区別する。
    """
    pairs = [row["comparison"] for row in rows if "comparison" in row]
    distances = [pair["dominant_oklab_distance"] for pair in pairs]
    if any(not math.isfinite(value) or value < 0 for value in distances):
        raise ValueError("主色距離は有限の非負値が必要です")
    masks = [mask for pair in pairs for mask in pair["mask_agreement"].values()
             if mask["group"] == "major"]
    if any(not 0 <= mask["intersection"] <= mask["union"] for mask in masks):
        raise ValueError("主要部位の画素集計が不正です")
    intersection, union = (sum(mask[key] for mask in masks) for key in ("intersection", "union"))
    distance = mean(distances) if distances else None
    agreement = intersection / union if union else None
    violations = []
    if distance is not None and distance > policy["dominant_oklab_mean_max"]:
        violations.append("dominant_oklab_mean")
    if agreement is not None and agreement < policy["major_agreement_min"]:
        violations.append("major_agreement")
    status = "warning" if violations else (
        "passed" if distance is not None and agreement is not None else "unevaluated"
    )
    if violations:
        logger.warning("縮小収集の許容差超過: %s", ", ".join(violations))
    return {
        "policy": policy, "evaluated": len(pairs), "unevaluated": len(rows) - len(pairs),
        "dominant_oklab_mean": distance, "major_agreement": agreement,
        "intersection": intersection, "union": union, "violations": violations, "status": status,
    }


def enqueue_audit(queue, comparison_path: Path, output_path: Path, *, code_version: str):
    """#90形式の比較JSONをreview jobへ固定する。入力の読取りとjob投入を行う。

    原本・縮小の対応解析後に呼ぶ。既存asset/runは変更せず、workerは本moduleを使う。
    """
    payload = {
        "comparison_path": str(comparison_path.resolve()),
        "comparison_sha256": hashlib.sha256(comparison_path.read_bytes()).hexdigest(),
        "output_path": str(output_path.resolve()), "quality_policy": QUALITY_POLICY,
        "code_version": code_version,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return queue.enqueue("review", None, digest, payload)


def prepare(claim):
    """原本再判定または監査を準備する。通信失敗は伝播し、暗黙の代替取得はしない。"""
    payload = claim.payload
    if "comparison_path" in payload:
        content = Path(payload["comparison_path"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != payload["comparison_sha256"]:
            raise ValueError("投入後に比較入力が変更されました")
        result = audit(json.loads(content), payload["quality_policy"])
        target = Path(payload["output_path"])
        temporary = temporary_path(target, str(claim.token))
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        return Prepared(RunInfo(
            "restricted", payload["code_version"], "0.1.0", "quality-audit",
            {**payload, "audit": result},
        ), {}, [(temporary, target)])
    from colorstats.collect import stage
    from colorstats.collect.measurement import Meter

    engine = create_engine(os.environ["DATABASE_URL"])
    meter = None
    try:
        if "measurement" in payload.get("bias", {}):
            meter = Meter(Queue(engine), claim)
        prepared = stage.prepare(claim, observer=meter.observe if meter else None)
        from colorstats.analyze.prep import _inspect, _quality

        for record in list(prepared.data["records"]):
            temporary, target = next(pair for pair in prepared.files
                                     if str(pair[1]) == record["target"])
            reason = None
            try:
                inspected = _inspect(temporary)
                if max(inspected["width"], inspected["height"]) < payload["quality_policy"][
                    "min_long_edge"
                ]:
                    reason = "below_min_resolution"
                else:
                    record["quality"] = _quality(inspected)
            except Image.DecompressionBombError:
                reason = "original_quality_image_limit"
            except (OSError, ValueError):
                reason = "original_quality_unreadable"
            if reason:
                temporary.unlink()
                prepared.files.remove((temporary, target))
                prepared.data["records"].remove(record)
                candidate = record["candidate"]
                prepared.info.parameters["skipped"].append({
                    "source_url": candidate["source_url"],
                    "original_url": candidate["original_url"],
                    "rank": candidate["rank"], "reason": reason,
                })
        if meter:
            meter.finish("prepared", parameters={"search": prepared.info.parameters})
            prepared.data["measurement_run_id"] = str(meter.id)
        return prepared
    except BaseException as error:
        if meter:
            meter.finish("failed", error=error)
        raise
    finally:
        engine.dispose()


def register(session, run, data):
    """再取得結果を新しいrunだけに記録し、元asset・収集runを変更しない。"""
    if data:
        from colorstats.collect import stage

        stage.register(session, run, data)
        if "measurement_run_id" in data:
            trial = session.get(ProcessingRun, data["measurement_run_id"])
            trial.parameters = {**trial.parameters, "state": "reviewed",
                                "review_run_id": str(run.id)}
