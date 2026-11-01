"""パイロットの後続投入とprep後のprovenance保持を検証する。"""

import errno
import json
import os
from pathlib import Path

import pytest
from ops.deploy.pilot import enqueue_analysis, report
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from colorstats.analyze.prep import register
from colorstats.queue import RunInfo
from colorstats.queue.worker import Worker
from colorstats.schema.models import Asset, Job, ProcessingRun
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import make_available
from tests.test_queue import queue as queue

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="CIのPostgreSQL専用"
)


def test_analysis_waits_for_prep_and_keeps_immutable_input(queue, asset, tmp_path):
    enqueue_analysis(queue, tmp_path, "pilot-test")
    enqueue_analysis(queue, tmp_path, "pilot-test")
    claim = queue.claim(["prep"])
    assert queue.claim(["color"]) is None
    target = tmp_path / "pilot-m1" / str(asset) / "prep.jpg"
    temporary = target.with_suffix(".tmp")
    temporary.parent.mkdir(parents=True)
    temporary.write_bytes(b"resized")
    run_id = queue.complete(
        claim, RunInfo("open", "pilot-test", "0.1.0", "test", {}),
        lambda session, run: None, [(temporary, target)],
    )
    enqueue_analysis(queue, tmp_path, "pilot-test")
    enqueue_analysis(queue, tmp_path, "pilot-test")
    with Session(queue.engine) as session:
        jobs = session.scalars(select(Job)).all()
        assert len(jobs) == 2
        color = next(job for job in jobs if job.stage == "color")
        run = session.get(ProcessingRun, run_id)
        assert color.payload["input_run_id"] == str(run_id)
        assert color.payload["input_path"] == run.output_paths[str(target)]
        assert color.payload["input_path"] != str(target)


def test_prep_preserves_collection_provenance(queue, asset):
    snapshot = {"author": "作者", "attribution": "帰属", "metadata": {"license": "cc0"}}
    with Session(queue.engine) as session, session.begin():
        session.get(Asset, asset).quality = snapshot
        register(session, None, {
            "asset_id": asset, "sha256": "b" * 64, "phash": "0" * 16,
            "width": 512, "height": 384, "colors": 257,
            "luminance": 100, "sharpness": 200,
            "watermark_suspected": False, "collage_suspected": False,
        })
    with Session(queue.engine) as session:
        quality = session.get(Asset, asset).quality
        assert all(quality[key] == value for key, value in snapshot.items())
        assert quality["resolution_ok"] is True


def test_report_serializes_postgresql_capacity_as_integer(queue, asset):
    result = report(queue.engine, {"strata": [], "limits": {"author_share": 0.05}})
    assert result["images"] == 1
    assert isinstance(result["database_bytes"], int)
    assert isinstance(result["table_bytes"], int)
    assert json.loads(json.dumps(result))["table_bytes"] > 0


@pytest.mark.parametrize("error", [FileNotFoundError, OSError])
def test_report_records_file_errors_and_allows_next_enqueue(
    queue, asset, tmp_path, monkeypatch, error
):
    target = tmp_path / "prep.jpg"
    temporary = tmp_path / "prep.tmp"
    temporary.write_bytes(b"resized")
    good = tmp_path / "other.tmp"
    good.write_bytes(b"valid")
    queue.enqueue("prep", asset, "test-report", {})
    claim = queue.claim(["prep"])
    queue.complete(
        claim, RunInfo("open", "test", "0.1.0", "test", {}),
        lambda session, run: None, [(temporary, target), (good, tmp_path / "other.jpg")],
    )
    original_stat = Path.stat

    def stat(path, *args, **kwargs):
        if path.name == "prep.jpg":
            raise error(errno.ENOENT if error is FileNotFoundError else errno.EIO, "test")
        return original_stat(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "stat", stat)
        result = report(queue.engine, {"strata": [], "limits": {"author_share": 0.05}})
    capacity = result["stages"]["prep"]
    assert capacity["capacity_complete"] is False
    assert capacity["bytes"] == 5
    assert capacity["files"] == 2
    assert capacity["file_errors"][0]["error"] == error.__name__
    json.dumps(result)
    enqueue_analysis(queue, tmp_path, "after-report")
    assert queue.claim(["prep"]) is not None


def test_publication_io_error_defers_without_consuming_attempt_and_resumes(
    queue, asset, tmp_path, monkeypatch
):
    source = tmp_path / "input.png"
    Image.new("RGB", (256, 256), "gray").save(source)
    target = tmp_path / "prep.jpg"
    job_id = queue.enqueue("prep", asset, "nfs-test", {
        "input_path": str(source), "derived_path": str(target),
        "license_class": "open", "taxonomy_version": "0.1.0",
    })
    worker = Worker(
        queue, {"prep": "colorstats.analyze.prep"}, tmp_path / "stop",
        storage_paths={"prep": (tmp_path,)},
    )

    def unavailable(path, destination):
        raise OSError(errno.EIO, "NFS timeout")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", unavailable)
        worker.run(once=True)
    with Session(queue.engine) as session:
        job = session.get(Job, job_id)
        assert job.status == "pending" and job.attempts == 0 and job.run_id is None
        assert session.scalars(select(ProcessingRun)).all() == []
    assert queue.claim(["prep"]) is None
    make_available(queue, job_id)
    worker.run(once=True)
    with Session(queue.engine) as session:
        job = session.get(Job, job_id)
        assert job.status == "succeeded" and job.attempts == 1
        output = session.get(ProcessingRun, job.run_id).output_paths[str(target)]
        with Image.open(output) as image:
            assert image.size == (256, 256)
