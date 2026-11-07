import copy
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from colorstats import image_gate, retention
from colorstats import privacy_review as privacy
from colorstats.analyze import color, region_policy, shade
from colorstats.api_budget import digest
from colorstats.queue import RunInfo
from colorstats.queue.worker import Worker
from colorstats.schema.models import Asset, Job, ProcessingRun, ProcessingRunInput, Subject
from colorstats.stats.snapshot import execute
from tests.test_image_gate import verdict
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue
from tests.test_region_policy import regional_payload as regional_payload
from tests.test_region_policy_db import policy_source as policy_source
from tests.test_segment import payload as payload
from tests.test_segment_db import prep_source as prep_source

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="隔離DB専用")


@pytest.fixture
def review_source(queue, asset, policy_source, tmp_path):
    raw = tmp_path / "acquired.png"
    Image.new("RGB", (128, 64), "red").save(raw)
    sha = hashlib.sha256(raw.read_bytes()).hexdigest()
    with Session(queue.engine) as session, session.begin():
        row = session.get(Asset, asset)
        row.storage_path, row.sha256 = str(raw), sha
        row.quality = {"privacy_review": {"reviewer": "旧確認者", "subject": "building"}}
        prep_job = session.scalar(select(Job).where(Job.run_id == policy_source["input_run_id"]))
        prep_job.payload = {"input_path": str(raw)}
        prep = session.get(ProcessingRun, policy_source["input_run_id"])
        prep.parameters = {**prep.parameters, "input_sha256": sha}
        segment = session.get(ProcessingRun, policy_source["region_run_id"])
        contract = copy.deepcopy(segment.parameters["region_policy"])
        for name in ("semantic", "person"):
            # 元fixtureの座標寸法を維持する。
            ref = contract["semantic"] if name == "semantic" else contract["exclusions"][name]
            path = Path(segment.output_paths[ref["path"]])
            with Image.open(path) as image:
                array = np.zeros((image.height, image.width), dtype=np.uint8)
            Image.fromarray(array).save(path)
            ref["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        segment.parameters = {**segment.parameters, "region_policy": contract}
        policy_source["region_policy"] = region_policy.reference(segment)
    result = tmp_path / "gate.json"
    result.write_text(json.dumps({"result": verdict(), "error": None}), encoding="utf-8")
    parameters = {"kind": "image_gate", "asset_id": str(asset),
                  "source_sha256": sha, "identity": image_gate.identity(image_gate.normalize(
                      raw.read_bytes())), "verdict": image_gate.decision(verdict()),
                  "result_path": str(result), "result_sha256": hashlib.sha256(
                      result.read_bytes()).hexdigest(), "method": "api", "input_run_id": None}
    job = queue.enqueue("review", asset, digest(parameters), parameters)
    claim = queue.claim(("review",), job_ids=[job])
    gate_id = queue.complete(claim, RunInfo("open", "test", "0.1.0", "fixture", parameters),
                             lambda s, r: None)
    return policy_source, gate_id, sha


def write(queue, asset, source, **kwargs):
    payload, gate_id, _ = source
    return privacy.write(queue, asset, gate_id, payload["region_run_id"],
                         code_version="test", **kwargs)


@pytest.mark.parametrize("stage", ["color", "shade"])
def test_人物承認を解析とsnapshotへ固定する(queue, asset, review_source, stage, tmp_path):
    rid = write(queue, asset, review_source)
    source, _, _ = review_source
    with Session(queue.engine) as session:
        row = privacy.selection(session, asset, rid)
        assert row["image_gate_input_sha256"] != row["input_sha256"]
    payload = {**source, **row, **({"method": "none"} if stage == "shade" else {})}
    handler = color if stage == "color" else shade
    job = queue.enqueue(stage, asset, handler.config_hash(payload), payload)
    claim = queue.claim((stage,), job_ids=[job])
    queue.check_input(claim)
    prepared = handler.prepare(claim)
    run_id = queue.complete(claim, prepared.info,
                            lambda s, r: handler.register(s, r, prepared.data), prepared.files)
    with Session(queue.engine) as session:
        assert session.get(ProcessingRunInput, (run_id, rid))
        assert session.get(Asset, asset).quality["privacy_review"]["reviewer"] == "旧確認者"
    if stage == "color":
        from tests.test_stats_snapshot_db import QUALITY

        quality = copy.deepcopy(QUALITY)
        quality["segment"] = {"method": region_policy.METHOD}
        selection = {"taxonomy_version": "0.1.0", "assets": [{**row,
            "prep_run_id": source["input_run_id"], "segment_run_id": source["region_run_id"],
            "color_run_id": str(run_id)}]}
        execute(queue.engine, selection, tmp_path / "snapshot", quality=quality,
                code_version="test")
        write(queue, asset, review_source, input_run_id=rid, reviewer="確認者",
              real_people="present", presented_source_sha256=review_source[2], note="小人物")
        with pytest.raises(PermissionError, match="失効"):
            execute(queue.engine, selection, tmp_path / "stale", quality=quality,
                    code_version="test")


def test_人の訂正は別runで旧runとqualityを保全し承認を失効する(queue, asset, review_source):
    rid = write(queue, asset, review_source)
    human = write(queue, asset, review_source, input_run_id=rid, reviewer="確認者",
                  real_people="present", presented_source_sha256=review_source[2], note="群衆")
    with Session(queue.engine) as session:
        assert session.get(ProcessingRun, rid).parameters["verdict"]["decision"] == "accepted"
        assert session.get(ProcessingRunInput, (human, rid))
        with pytest.raises(PermissionError, match="失効"):
            privacy.selection(session, asset, rid)
        with pytest.raises(PermissionError, match="保留"):
            privacy.selection(session, asset, human)
        frozen = privacy.evaluation_input(session, [(asset, human, "challenge")])
        assert frozen["samples"][0]["review"]["verdict"]["decision"] == "pending"
        assert frozen == privacy.evaluation_input(session, [(asset, human, "challenge")])
        with pytest.raises(ValueError, match="重複"):
            privacy.evaluation_input(session, [(asset, human, "challenge"),
                                               (asset, human, "random_new")])


@pytest.mark.parametrize("key", privacy.FIELDS)
def test_SHA寸法runの差替えを旧qualityへ代替しない(queue, asset, review_source, key):
    rid = write(queue, asset, review_source)
    with Session(queue.engine) as session:
        row = privacy.selection(session, asset, rid)
        row[key] = None
        with pytest.raises((PermissionError, ValueError, TypeError, AttributeError)):
            retention.check_privacy(session, asset, row)


def test_人物画素の改変と像の不一致は採用しない(queue, asset, review_source):
    source, _, _ = review_source
    with Session(queue.engine) as session, session.begin():
        segment = session.get(ProcessingRun, source["region_run_id"])
        contract = copy.deepcopy(segment.parameters["region_policy"])
        for name in ("semantic", "person"):
            ref = contract["semantic"] if name == "semantic" else contract["exclusions"][name]
            path = Path(segment.output_paths[ref["path"]])
            array = np.array(Image.open(path))
            array[0, 1] = 12 if name == "semantic" else 255
            Image.fromarray(array).save(path)
            ref["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        segment.parameters = {**segment.parameters, "region_policy": contract}
    rid = write(queue, asset, review_source)
    with Session(queue.engine) as session:
        assert session.get(ProcessingRun, rid).parameters["verdict"]["reason"] == "disagreement"
        with pytest.raises(PermissionError):
            privacy.selection(session, asset, rid)
    human = write(queue, asset, review_source, input_run_id=rid, reviewer="確認者",
                  real_people="absent", presented_source_sha256=review_source[2], note="像")
    with Session(queue.engine) as session, pytest.raises(PermissionError, match="保留"):
        privacy.selection(session, asset, human)


def test_未提示の訂正は拒否する(queue, asset, review_source):
    rid = write(queue, asset, review_source)
    with pytest.raises(ValueError, match="提示画像"):
        write(queue, asset, review_source, input_run_id=rid, reviewer="確認者",
              real_people="absent", presented_source_sha256="unpresented", note="像")


@pytest.mark.parametrize("change", ["mask_missing", "mask_mismatch", "prep_sha", "policy"])
def test_証拠欠落と改変で承認を引き継がない(queue, asset, review_source, change):
    rid = write(queue, asset, review_source)
    source, _, _ = review_source
    with Session(queue.engine) as session, session.begin():
        segment = session.get(ProcessingRun, source["region_run_id"])
        if change.startswith("mask"):
            contract = copy.deepcopy(segment.parameters["region_policy"])
            ref = contract["exclusions"]["person"]
            path = Path(segment.output_paths[ref["path"]])
            if change == "mask_missing":
                path.unlink()
            else:
                array = np.array(Image.open(path))
                array[0, 1] = 255
                Image.fromarray(array).save(path)
                ref["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                segment.parameters = {**segment.parameters, "region_policy": contract}
        elif change == "prep_sha":
            prep = session.get(ProcessingRun, source["input_run_id"])
            prep.parameters = {**prep.parameters, "input_sha256": "old-source"}
        else:
            run = session.get(ProcessingRun, rid)
            parameters = copy.deepcopy(run.parameters)
            parameters["evidence"]["policy_hash"] = "old-policy"
            run.parameters = parameters
    with Session(queue.engine) as session, pytest.raises((PermissionError, FileNotFoundError)):
        privacy.selection(session, asset, rid)


def test_画像判定の訂正も以前の解析承認を失効する(queue, asset, review_source):
    rid = write(queue, asset, review_source)
    assert write(queue, asset, review_source) == rid
    with Session(queue.engine) as session:
        gate = session.get(ProcessingRun, review_source[1])
        parameters = {**gate.parameters, "input_run_id": str(gate.id), "method": "human"}
    job = queue.enqueue("review", asset, digest(parameters), parameters)
    claim = queue.claim(("review",), job_ids=[job])
    queue.complete(claim, RunInfo("open", "test", "0.1.0", "fixture", parameters),
                   lambda s, r: None)
    with Session(queue.engine) as session, pytest.raises(PermissionError, match="失効"):
        privacy.selection(session, asset, rid)


def test_review_workerが停止後の人物reviewを専用writerで再開する(
    queue, asset, review_source, monkeypatch, tmp_path,
):
    with monkeypatch.context() as context:
        context.setattr(queue, "claim", lambda *a, **kw: None)
        with pytest.raises(RuntimeError, match="処理中"):
            write(queue, asset, review_source)
    claim = queue.claim(("review",))
    worker = Worker(queue, {"review": "colorstats.collect.quality"}, tmp_path / "stop")
    try:
        worker._run_claim(claim)
    finally:
        worker._stop_prepare()
    with Session(queue.engine) as session:
        job = session.get(Job, claim.id)
        assert job.status == "succeeded"
        assert privacy.selection(session, asset, job.run_id)["privacy_review_run_id"]


def test_同じdomainでもsubject変更後の承認は失効する(queue, asset, review_source):
    rid = write(queue, asset, review_source)
    with Session(queue.engine) as session, session.begin():
        subject = Subject(name="合成建物", domain="real_building", taxonomy_version="0.1.0",
                          scene_attributes={})
        session.add(subject)
        session.flush()
        session.get(Asset, asset).subject_id = subject.id
    with Session(queue.engine) as session, pytest.raises(PermissionError, match="変更"):
        privacy.selection(session, asset, rid)
