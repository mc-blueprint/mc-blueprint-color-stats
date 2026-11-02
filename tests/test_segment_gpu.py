"""明示指定時のみ、一時DBのschemaと自作画像で実GPUワーカーを確認する。"""

import json
import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.orm import Session

from colorstats.analyze.segment import config_hash
from colorstats.queue.worker import Worker
from colorstats.schema.models import Job, ProcessingRun, Region
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue

pytestmark = pytest.mark.skipif(
    not os.environ.get("SEGMENT_GPU_MODELS") or not os.environ.get("TEST_DATABASE_URL"),
    reason="公式重み・CUDA・一時テストDBの明示指定が必要",
)


def test_gpu_worker(queue, asset, tmp_path):
    models = Path(os.environ["SEGMENT_GPU_MODELS"])
    image = Image.new("RGB", (512, 384), "skyblue")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 310, 511, 383), fill="forestgreen")
    draw.rectangle((105, 155, 405, 320), fill="burlywood", outline="black", width=3)
    draw.polygon([(80, 160), (255, 40), (430, 160)], fill="firebrick", outline="black")
    draw.rectangle((225, 230, 280, 320), fill="saddlebrown", outline="black", width=3)
    for x in (135, 320):
        draw.rectangle((x, 195, x + 45, 245), fill="lightblue", outline="black", width=4)
    source = tmp_path / "self-made-house.png"
    image.save(source)
    paths = {name: str(models / name) for name in ("sam2", "dino")}
    payload = {
        "method": "sam2-dino", "model_paths": paths, "input_path": str(source),
        "output_path": str(tmp_path / "segments.json"), "license_class": "open",
        "taxonomy_version": "0.1.0", "threshold": 0.25,
        "prompts": {"wall_main": "building wall", "roof_surface": "roof",
                    "door": "door", "ground_grass": "grass"},
    }
    job_id = queue.enqueue("segment", asset, config_hash(payload), payload)
    Worker(queue, {"segment": "colorstats.analyze.segment"}, tmp_path / "stop").run(once=True)
    with Session(queue.engine) as session:
        job = session.get(Job, job_id)
        assert job.status == "succeeded", job.failure_reason
        run = session.get(ProcessingRun, job.run_id)
        regions = session.scalars(select(Region).where(Region.processing_run_id == run.id)).all()
        assert regions, "自作家屋で部位が検出されませんでした"
        assert all(Path(region.mask_path).is_file() for region in regions)
        report = {
            "model_name": run.model_name, "weights_hash": run.weights_hash,
            "config_hash": run.config_hash, "license_class": run.license_class,
            "parameters": run.parameters, "output_paths": run.output_paths,
            "output_bytes": sum(Path(path).stat().st_size for path in run.output_paths.values()),
            "labels": [region.label for region in regions],
            "input_license": "自作テスト画像・CC0",
        }
        if destination := os.environ.get("SEGMENT_GPU_REPORT"):
            Path(destination).write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        print(json.dumps(report, ensure_ascii=False))
