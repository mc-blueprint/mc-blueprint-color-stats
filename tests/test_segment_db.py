import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from colorstats.analyze import segment
from colorstats.queue import RunInfo
from colorstats.schema.models import Job, ProcessingRun, ProcessingRunInput, Region
from colorstats.store import temporary_path
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue
from tests.test_segment import payload as payload
from tests.test_segment import prediction

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="CIのPostgreSQL専用"
)


@pytest.fixture
def prep_source(queue, asset, payload):
    queue.enqueue("prep", asset, "b" * 64, {})
    claim = queue.claim(("prep",))
    target = Path(payload["input_path"])
    temporary = temporary_path(target, str(claim.token))
    temporary.write_bytes(target.read_bytes())
    input_id = queue.complete(
        claim, RunInfo("noncommercial", "test", "0.1.0", "test", {}),
        lambda session, run: None, [(temporary, target)],
    )
    with Session(queue.engine) as session:
        payload["input_path"] = session.get(ProcessingRun, input_id).output_paths[str(target)]
    payload["input_run_id"] = str(input_id)
    return input_id


def test_immutable_masks_provenance_and_license(queue, asset, payload, monkeypatch, prep_source):
    monkeypatch.setattr(segment, "predict", prediction)
    input_id = prep_source
    queue.enqueue("segment", asset, segment.config_hash(payload), payload)
    claim = queue.claim(("segment",))
    result = segment.prepare(claim)

    def register(session, run):
        segment.register(session, run, result.data)

    run_id = queue.complete(claim, result.info, register, result.files)
    assert queue.complete(claim, result.info, register, result.files) == run_id
    with Session(queue.engine) as session:
        run = session.get(ProcessingRun, run_id)
        assert run.model_name == "sam2-dino"
        assert run.license_class == "noncommercial"
        assert run.config_hash == claim.config_hash
        assert session.get(ProcessingRunInput, (run_id, input_id)) is not None
        assert session.scalar(select(func.count()).select_from(Region)) == 1
        region = session.scalars(select(Region)).one()
        assert region.asset_id == asset and region.label_source == "model"
        assert Path(region.mask_path).is_file()
        assert region.mask_path == run.output_paths[result.data["regions"][0]["mask_path"]]
        assert not Path(result.data["regions"][0]["mask_path"]).exists()
        assert region.normalized_height is None


@pytest.mark.parametrize("mismatch", [
    "missing", "stage", "unfinished", "failed", "asset", "output_name", "path", "no_outputs",
])
def test_invalid_input_run_rolls_back(queue, asset, payload, monkeypatch, prep_source, mismatch):
    monkeypatch.setattr(segment, "predict", prediction)
    with Session(queue.engine) as session, session.begin():
        source = session.get(ProcessingRun, prep_source)
        if mismatch == "missing":
            payload["input_run_id"] = str(uuid.uuid4())
        elif mismatch == "stage":
            source.stage = "color"
        elif mismatch == "unfinished":
            source.finished_at = None
        elif mismatch == "failed":
            source.failure_reason = "前処理失敗"
        elif mismatch == "asset":
            session.scalar(select(Job).where(Job.run_id == prep_source)).asset_id = None
        elif mismatch == "output_name":
            payload["input_path"] = next(iter(source.output_paths))
        elif mismatch == "path":
            other = Path(payload["input_path"]).with_name("other.png")
            other.write_bytes(Path(payload["input_path"]).read_bytes())
            payload["input_path"] = str(other)
        elif mismatch == "no_outputs":
            source.output_paths = {}
    job_id = queue.enqueue("segment", asset, segment.config_hash(payload), payload)
    claim = queue.claim(("segment",))
    result = segment.prepare(claim)
    with pytest.raises(ValueError, match="同じassetの成功済みprep") as error:
        queue.complete(
            claim, result.info,
            lambda session, run: segment.register(session, run, result.data), result.files,
        )
    queue.fail(claim, str(error.value))
    with Session(queue.engine) as session:
        job = session.get(Job, job_id)
        assert job.status == "pending" and job.run_id is None
        assert "同じassetの成功済みprep" in job.failure_reason
        assert session.scalar(select(func.count()).select_from(Region)) == 0
        assert session.scalar(select(func.count()).select_from(ProcessingRunInput)) == 0
        assert session.scalar(select(func.count()).select_from(ProcessingRun)) == 1
