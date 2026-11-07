import json
import os
from contextlib import nullcontext
from pathlib import Path

import pytest
from ops.deploy import m3_analysis
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from colorstats.analyze import color, segment, segment_models, shade
from colorstats.schema.models import Job, ProcessingRun
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue
from tests.test_segment import payload as payload
from tests.test_segment import prediction


def test_resident_models_reuse_content_and_invalidate(monkeypatch):
    calls = []
    monkeypatch.setattr(segment_models, "_sam2", lambda paths: calls.append(paths) or object())
    segment_models._resident.cache_clear()
    paths = (("dino", "/models/dino"), ("sam2", "/models/sam2"))
    a = segment_models._resident(paths, (("model", "a"),))
    assert segment_models._resident(paths, (("model", "a"),)) is a
    assert segment_models._resident(paths, (("model", "b"),)) is not a
    assert len(calls) == 2
    segment_models._resident.cache_clear()


def test_predict_reuses_configuration_model_hashes(monkeypatch):
    import sys
    from types import SimpleNamespace

    class Cuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def reset_peak_memory_stats():
            pass

        @staticmethod
        def synchronize():
            pass

        @staticmethod
        def max_memory_allocated():
            return 0

        @staticmethod
        def max_memory_reserved():
            return 0

        @staticmethod
        def get_device_name():
            return "test"

    torch = SimpleNamespace(
        cuda=Cuda(), manual_seed=lambda seed: None, inference_mode=nullcontext,
        autocast=lambda *args, **kwargs: nullcontext(), bfloat16=object(),
        __version__="test", version=SimpleNamespace(cuda="test"),
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    seen = {}
    monkeypatch.setattr(
        segment_models, "_resident",
        lambda paths, files: seen.update(paths=paths, files=files) or (lambda *args: []),
    )
    paths = {"sam2": "/missing/sam2", "dino": "/missing/dino"}
    model_hashes = {
        "sam2": {"files": {"weights.safetensors": "s"}},
        "dino": {"files": {"config.json": "d", "weights.safetensors": "w"}},
    }

    segment_models.predict(
        object(), "sam2-dino", paths, model_hashes, {}, 0.35, 0.25,
    )

    assert seen["files"] == (
        (str(Path(paths["dino"]) / "config.json"), "d"),
        (str(Path(paths["dino"]) / "weights.safetensors"), "w"),
        (str(Path(paths["sam2"]) / "weights.safetensors"), "s"),
    )


def test_process_io_avoids_recounting_reaped_child():
    keys = ("rchar", "wchar", "read_bytes", "write_bytes")
    attempts = [
        {"event": "started", "io": {"parent": dict(zip(keys, (100, 50, 10, 20), strict=True))}},
        {"event": "finished", "io": {
            "parent": dict(zip(keys, (110, 55, 11, 22), strict=True)),
            "child-1": dict(zip(keys, (10, 5, 1, 2), strict=True)),
        }},
        {"event": "started", "io": {"parent": dict(zip(keys, (120, 60, 12, 24), strict=True))}},
        {"event": "finished", "io": {
            "parent": dict(zip(keys, (125, 62, 13, 26), strict=True)),
            "child-2": dict(zip(keys, (8, 4, 1, 1), strict=True)),
        }},
    ]

    assert m3_analysis._process_io_bytes(attempts) == {
        "rchar": 33, "wchar": 16, "read_bytes": 4, "write_bytes": 7,
    }


def test_report_violations_raise_for_cli(monkeypatch, tmp_path):
    import sys

    class Engine:
        disposed = False

        def dispose(self):
            self.disposed = True

    root = tmp_path / "report-root"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps({"assets": []}))
    monkeypatch.setattr(sys, "argv", [
        "m3_analysis", "report", "--root", str(root), "--output", str(root / "report.json"),
    ])
    monkeypatch.setattr(m3_analysis, "report", lambda *args: {"violations": ["test"]})
    engine = Engine()

    with pytest.raises(ValueError, match="report integrity violations: 1"):
        m3_analysis.main(engine)

    assert engine.disposed


@pytest.mark.parametrize("handler", [segment, shade, color])
def test_replaced_image_rejected_before_enqueue(payload, handler):
    payload.update(input_sha256=segment._hash(payload["input_path"]),
                   region_run_id="test", regions=[])
    if handler is shade:
        payload["method"] = "none"
    Image.new("RGB", (8, 6), "blue").save(payload["input_path"])
    with pytest.raises(ValueError, match="SHA-256"):
        handler.config_hash(payload)


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="隔離PostgreSQL専用")
def test_claim_scopes_jobs_without_consuming_others(queue, asset):
    other = queue.enqueue("segment", asset, "a" * 64, {})
    own = queue.enqueue("segment", asset, "b" * 64, {})
    assert queue.claim(("segment",), job_ids=[]) is None
    assert queue.claim(("segment",), job_ids=[own]).id == own
    with Session(queue.engine) as session:
        job = session.get(Job, other)
        assert job.status == "pending" and job.attempts == 0


@pytest.mark.skipif(os.name != "posix" or not os.environ.get("TEST_DATABASE_URL"),
                    reason="Linux・隔離PostgreSQL専用")
def test_pipeline_restart_registration_and_retry_audit(
    queue, asset, payload, tmp_path, monkeypatch,
):
    root = tmp_path / "batch"
    root.mkdir()
    (root / "outputs").mkdir()
    image = Path(payload["input_path"])
    prep_id = queue.enqueue("prep", asset, "a" * 64, {})
    prep_claim = queue.claim(("prep",), job_ids=[prep_id])
    temporary = image.with_name(".prep")
    temporary.write_bytes(image.read_bytes())
    from colorstats.queue.core import RunInfo

    prep_run = queue.complete(prep_claim, RunInfo("open", "test", "0.1.0", "test", {}),
                              lambda *args: None, [(temporary, image)])
    with Session(queue.engine) as session:
        path = session.get(ProcessingRun, prep_run).output_paths[str(image)]
    row = {"asset_id": str(asset), "sha256": "a" * 64, "prep_status": "succeeded",
           "license_class": "open", "taxonomy_version": "0.1.0", "input_run_id": str(prep_run),
           "input_path": path, "input_sha256": segment._hash(path),
           "input_bytes": Path(path).stat().st_size}
    manifest = {"assets": [row], "settings": {
        "segment": {"method": "sam2-dino", "prompts": payload["prompts"]},
        "shade": {"method": "none"}, "quality": {"supported_labels": ["door"]},
    }, "implementation": m3_analysis.implementation()}
    m3_analysis.save(root / "manifest.json", manifest)
    monkeypatch.setattr(m3_analysis, "Sampler", lambda path: nullcontext())
    monkeypatch.setattr(segment, "predict", prediction)
    original_files = payload["model_paths"]
    models = tmp_path / "models"
    models.mkdir()
    for name, source in original_files.items():
        import shutil

        shutil.copytree(source, models / name)
    seen = []

    def execute(worker, claim):
        seen.append(claim.stage)
        if len(seen) == 1:
            worker.queue.fail(claim, "検証用の一時失敗")
            return
        handler = {"segment": segment, "shade": shade, "color": color}[claim.stage]
        prepared = handler.prepare(claim)
        worker.queue.complete(claim, prepared.info,
                              lambda s, r: handler.register(s, r, prepared.data), prepared.files)

    monkeypatch.setattr(m3_analysis.Worker, "_run_claim", execute)
    m3_analysis.run_batch(queue.engine, root, manifest, models, None)
    result = m3_analysis.report(queue.engine, root, manifest, root / "report1.json")
    assert result["completed_assets"] == 1 and not result["violations"]
    assert result["stages"]["segment"]["retries"] == 1
    assert result["attempt_events"]["finished"] == 4
    assert result["stages"]["shade"]["part_observations"] == 1
    assert result["stages"]["color"]["part_observations"] >= 1
    with Session(queue.engine) as session:
        run_ids = list(session.scalars(select(Job.run_id).where(Job.stage.in_(m3_analysis.STAGES))))
    m3_analysis.run_batch(queue.engine, root, manifest, models, None)
    with Session(queue.engine) as session:
        assert list(session.scalars(select(Job.run_id).where(
            Job.stage.in_(m3_analysis.STAGES)))) == run_ids
    assert len(seen) == 4
    data = json.loads((root / "report1.json").read_text())
    assert data["unclosed_attempts"] == 0

    from colorstats.schema.models import Asset

    person_mask = tmp_path / "people.png"
    people = Image.new("L", Image.open(path).size, 0)
    people.putpixel((0, 0), 255)
    people.save(person_mask)
    with Session(queue.engine) as session, session.begin():
        item = session.get(Asset, asset)
        item.quality = {**item.quality, "privacy_review": {
            "reviewer": "test", "subject": "building", "person_mask": str(person_mask),
            "mask_sha256": segment._hash(person_mask),
        }}
    reuse = tmp_path / "reuse"
    reuse.mkdir()
    (reuse / "outputs").mkdir()
    m3_analysis.freeze(queue.engine, reuse, [str(asset)], reuse_segments=True)
    reused_manifest = json.loads((reuse / "manifest.json").read_text())
    assert reused_manifest["assets"][0]["person_mask"] == str(person_mask)
    m3_analysis.run_batch(queue.engine, reuse, reused_manifest, models, None)
    result = m3_analysis.report(queue.engine, reuse, reused_manifest, reuse / "report.json")
    assert result["completed_assets"] == 1 and not result["violations"]
    assert seen[4:] == ["shade", "color"]
    with Session(queue.engine) as session:
        jobs = session.scalars(select(Job).where(Job.payload["batch"].astext == segment._hash(
            reuse / "manifest.json"))).all()
        assert {job.stage for job in jobs} == {"shade", "color"}
        assert all(job.payload["person_mask"] == str(person_mask) for job in jobs)


def test_runner_import_does_not_load_colour_before_transformers():
    import subprocess
    import sys

    subprocess.run([sys.executable, "-c",
                    "import sys; import ops.deploy.m3_analysis; "
                    "assert 'colour' not in sys.modules"], check=True)


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="隔離PostgreSQL専用")
def test_新規cohortだけを固定し欠落重複と未完了prepを拒否する(queue, asset, tmp_path):
    from uuid import uuid4

    from colorstats.queue import RunInfo

    root = tmp_path / "cohort"
    root.mkdir()
    queue.enqueue("prep", asset, "b" * 64, {})
    with pytest.raises(ValueError, match="未完了"):
        m3_analysis.freeze(queue.engine, root, [str(asset)])
    with pytest.raises(ValueError, match="重複"):
        m3_analysis.freeze(queue.engine, root, [str(asset), str(asset)])
    with pytest.raises(ValueError, match="存在しない"):
        m3_analysis.freeze(queue.engine, root, [str(uuid4())])
    temporary, final = tmp_path / "input.tmp", tmp_path / "input.png"
    Image.new("RGB", (5, 5), "red").save(temporary, format="PNG")
    input_digest = segment._hash(temporary)
    claim = queue.claim(["prep"])
    queue.complete(claim, RunInfo("open", "test", "0.1.0", "test", {}),
                   lambda *args: None, [(temporary, final)])
    m3_analysis.freeze(queue.engine, root, [str(asset)])
    manifest = json.loads((root / "manifest.json").read_text())
    assert [row["asset_id"] for row in manifest["assets"]] == [str(asset)]
    assert manifest["assets"][0]["input_sha256"] == input_digest
    with pytest.raises(FileExistsError):
        m3_analysis.freeze(queue.engine, root, [str(asset)])


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="隔離PostgreSQL専用")
def test_changed_segment_input_hash_rejects_registration(queue, asset, tmp_path):
    from sqlalchemy import func

    from colorstats.schema.models import ColorObservation
    from tests.test_part_color_db import part_payload

    payload = part_payload(queue, asset, tmp_path, "model")
    payload["input_sha256"] = segment._hash(payload["input_path"])
    job_id = queue.enqueue("color", asset, color.config_hash(payload), payload)
    claim = queue.claim(("color",), job_ids=[job_id])
    prepared = color.prepare(claim)
    with Session(queue.engine) as session, session.begin():
        source = session.get(ProcessingRun, payload["region_run_id"])
        source.parameters = {**source.parameters, "input_sha256": "f" * 64}
    with pytest.raises(ValueError, match="入力画像hash"):
        queue.complete(claim, prepared.info,
                       lambda s, r: color.register(s, r, prepared.data), prepared.files)
    with Session(queue.engine) as session:
        assert session.scalar(select(func.count()).select_from(ColorObservation)) == 0
        assert session.get(Job, job_id).run_id is None
