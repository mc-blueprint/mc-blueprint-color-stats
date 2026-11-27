"""新しいrunへの引継ぎを合成B・隔離DBで検証する。GPU・本番を使用しない。"""

import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

pytest.importorskip("pwd")

from bench.issue114 import mobile
from bench.issue114 import production as terrain_production
from bench.issue122 import production, runtime
from sqlalchemy import select
from sqlalchemy.orm import Session

from colorstats import privacy_review
from colorstats.analyze import color, shade
from colorstats.schema.models import Asset, Job, ProcessingRun
from tests import test_segment
from tests.test_issue120_db import presentation as presentation
from tests.test_privacy_review_db import review_source as review_source
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue
from tests.test_region_policy import regional_payload as regional_payload
from tests.test_region_policy_db import policy_source as policy_source
from tests.test_segment_db import prep_source as prep_source

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="隔離DB専用")


@pytest.fixture
def payload(tmp_path):
    return {**test_segment.payload.__wrapped__(tmp_path), "threshold": 0.35, "text_threshold": 0.25}


def source_data(queue, asset, review_source):
    source, gate, sha = review_source
    with Session(queue.engine) as session:
        job = session.scalar(select(Job).where(Job.run_id == UUID(source["region_run_id"])))
        run = session.get(ProcessingRun, job.run_id)
        settings = {k: job.payload[k] for k in ("method", "prompts")}
        settings.update({k: run.parameters[k] for k in ("threshold", "text_threshold")})
        models = Path(job.payload["model_paths"]["dino"]).parent
    row = {**source, "asset_id": str(asset), "sha256": sha, "image_gate_run_id": str(gate),
           "analysis_domain": "real_building", "status": "ready"}
    return row, settings, models


@pytest.mark.parametrize("change", [None, "input", "prompt", "mask", "model"])
def test_Bの成功と設定とmaskを照合して参照だけを引き継ぐ(
        queue, asset, review_source, change):
    row, settings, models = source_data(queue, asset, review_source)
    with Session(queue.engine) as session:
        before = copy.deepcopy(session.get(ProcessingRun, UUID(row["region_run_id"])).parameters)
        if change == "input":
            row["input_sha256"] = "0" * 64
        elif change == "prompt":
            settings["prompts"] = {"wall_main": "changed"}
        elif change == "mask":
            policy = review_source[0]["region_policy"]
            Path(policy["exclusions"]["person"]["path"]).write_bytes(b"changed")
        elif change == "model":
            (models / "dino/config.json").write_text("changed")
        if change:
            with pytest.raises(ValueError):
                runtime.segment_reference(session, row, row["region_run_id"], settings, models)
        else:
            assert runtime.segment_reference(session, row, row["region_run_id"], settings, models)
        assert session.get(ProcessingRun, UUID(row["region_run_id"])).parameters == before


def test_旧recordsからBだけを引き継ぎ旧人物承認や終結をコピーしない(
        queue, asset, review_source, tmp_path):
    row, settings, models = source_data(queue, asset, review_source)
    root = tmp_path / "old"
    (root / "ubuntu1").mkdir(parents=True)
    (root / "plan.json").write_text('{"partitions":["ubuntu1"]}')
    records = {str(asset): {"segment_run_id": row["region_run_id"],
                            "privacy_review_run_id": "old", "terminal": True}}
    path = root / "ubuntu1/records.json"
    path.write_text(json.dumps(records))
    original = path.read_bytes()
    with Session(queue.engine) as session:
        result = runtime.reused_segments(session, root, [row], settings, models)
        missing = {**row, "asset_id": "missing"}
        assert runtime.reused_segments(session, root, [missing], settings, models) == {}
    assert result == {str(asset): row["region_run_id"]}
    assert path.read_bytes() == original


def test_三段階の新runと停止後の再開が旧runとqualityを保存する(
        queue, asset, review_source, tmp_path, monkeypatch):
    row, settings, models = source_data(queue, asset, review_source)
    root = tmp_path / "restart"
    part = root / runtime.PARTITION
    part.mkdir(parents=True)
    plan = {"version": runtime.VERSION, "partitions": [runtime.PARTITION],
            "human_sampling": {"required_ids": [str(asset)], "seed": 169},
            "settings": settings, "rows": [row],
            "reused_segments": {str(asset): row["region_run_id"]}}
    production.save(root / "plan.json", plan)
    production.save(part / "inputs.json", [row])
    production.save(root / "execution.json", {"implementation": {}, "implementation_hash": "test",
                                             "plan_sha256": production.segment._hash(
                                                 root / "plan.json")})
    monkeypatch.setattr(production, "ROOT", root)
    monkeypatch.setattr(production, "implementation", lambda: {})
    monkeypatch.setattr(production, "check_models", lambda models: None)
    monkeypatch.setattr(production.subprocess, "check_output", lambda *a, **k: b"")
    monkeypatch.setattr(production, "Worker",
                        lambda *a: SimpleNamespace(_stop_prepare=lambda: None))
    stages = []

    def execute(q, worker, stage, row, payload):
        assert stage != "segment"
        stages.append(stage)
        handler = {"shade": shade, "color": color}[stage]
        job = q.enqueue(stage, asset, handler.config_hash(payload), payload)
        claim = q.claim((stage,), job_ids=[job])
        q.check_input(claim)
        prepared = handler.prepare(claim)
        return str(q.complete(claim, prepared.info,
                              lambda s, r: handler.register(s, r, prepared.data), prepared.files))

    monkeypatch.setattr(production, "execute_job", execute)
    with Session(queue.engine) as session:
        quality = copy.deepcopy(session.get(Asset, asset).quality)
        old = copy.deepcopy(session.get(ProcessingRun, UUID(row["region_run_id"])).parameters)
    production.run(queue.engine, runtime.PARTITION, models, 3)
    records = production.read(part / "records.json")
    current = UUID(records[str(asset)]["privacy_review_run_id"])
    production.run(queue.engine, runtime.PARTITION, models, None)
    assert stages == ["shade", "color"]
    assert production.read(part / "records.json") == records
    monkeypatch.setattr(terrain_production, "ROOT", root)
    terrain_production.audit(queue.engine, runtime.PARTITION, 3)
    assert production.read(part / "audit-smoke.json")["failures"] == 0
    with Session(queue.engine) as session:
        assert session.get(ProcessingRun, current).parameters["evidence"]["policy"] == (
            privacy_review.POLICY)
        assert session.get(Asset, asset).quality == quality
        assert session.get(ProcessingRun, UUID(row["region_run_id"])).parameters == old
    outputs = {p: p.read_bytes() for p in (part / "outputs").glob("*.json")}
    confirmed = privacy_review.write(
        queue, asset, row["image_gate_run_id"], row["region_run_id"], code_version="human-test",
        input_run_id=current, reviewer="ユーザー", presented_source_sha256=row["sha256"],
        real_people="absent", note="新しい目視確認",
    )
    (root / "human").mkdir()
    (root / "human/converted-review.json").write_text("{}")
    monkeypatch.setattr(runtime, "human_reviews", lambda *a: {str(asset): str(confirmed)})
    production.run(queue.engine, runtime.PARTITION, models, None)
    updated = production.read(part / "records.json")[str(asset)]
    assert updated["privacy_review_run_id"] == str(confirmed)
    assert updated["history"] == [records[str(asset)]]
    assert updated["segment_run_id"] == records[str(asset)]["segment_run_id"]
    assert updated["color_run_id"] != records[str(asset)]["color_run_id"]
    assert stages == ["shade", "color", "shade", "color"]
    assert all(p.read_bytes() == raw for p, raw in outputs.items())
    with Session(queue.engine) as session:
        job = session.scalar(select(Job).where(Job.run_id == UUID(updated["color_run_id"])))
        assert job.payload["privacy_review_run_id"] == str(confirmed)
        assert session.get(Asset, asset).quality == quality
    terrain_production.audit(queue.engine, runtime.PARTITION, None)
    assert production.read(part / "audit-full.json")["terminal"] == 1
    stale = copy.deepcopy(updated)
    stale["privacy_review_run_id"] = str(current)
    production.save(part / "records.json", {str(asset): stale})
    with pytest.raises(PermissionError):
        terrain_production.audit(queue.engine, runtime.PARTITION, None)
    production.save(part / "records.json", {str(asset): updated})
    production.save(part / "inputs.json", [])
    with pytest.raises(ValueError, match="入力subset"):
        production.run(queue.engine, runtime.PARTITION, models, None)


def test_新しい人確認と提示の対応だけを消費し元runを保存する(
        queue, asset, presentation, tmp_path):
    bundle, execution, _, rid = presentation
    human = tmp_path / "human"
    sampling = {"seed": 169, "criteria": {"max_problems": 0}, "required_ids": [str(asset)]}
    manifest = production.read(bundle / "manifest.json")
    manifest["sampling"] = sampling
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    (execution / "review-manifest.json").write_bytes((bundle / "manifest.json").read_bytes())
    mobile.build(queue.engine, bundle, execution, human, Path("taxonomy"))
    (human / "review-manifest.json").write_bytes((bundle / "manifest.json").read_bytes())
    mapping = production.read(human / "number-map.json")
    reply = mobile.reply_reviews(mapping, human / "review-manifest.json",
                                 manifest["decisions_sha256"], "全1枚確認済み\n問題なし",
                                 directory=human, db=queue.engine)
    applied = mobile.apply_privacy_reply(queue, reply)
    new_id = UUID(applied["rows"][0]["recorded_privacy_review_run_id"])
    path = human / "converted-review.json"
    path.write_text(json.dumps(applied))
    with Session(queue.engine) as session:
        assert runtime.human_reviews(session, tmp_path, {"human_sampling": sampling}) == {
            str(asset): str(new_id)}
        applied["rows"][0]["presented_source_sha256"] = "0" * 64
        path.write_text(json.dumps(applied))
        with pytest.raises(ValueError):
            runtime.human_reviews(session, tmp_path, {"human_sampling": sampling})
        assert session.get(ProcessingRun, rid).parameters["verdict"]["decision"] == "accepted"


@pytest.mark.parametrize("key", ["threshold", "text_threshold"])
@pytest.mark.parametrize("location", ["job", "run", "both"])
def test_省略閾値のBを統計より前に拒否する(queue, asset, review_source, key, location):
    row, settings, models = source_data(queue, asset, review_source)
    with Session(queue.engine) as session, session.begin():
        job = session.scalar(select(Job).where(Job.run_id == UUID(row["region_run_id"])))
        run = session.get(ProcessingRun, job.run_id)
        if location in {"job", "both"}:
            job.payload = {k: v for k, v in job.payload.items() if k != key}
        if location in {"run", "both"}:
            stored = {k: v for k, v in run.parameters["payload"].items() if k != key}
            run.parameters = {**run.parameters, "payload": stored}
    with Session(queue.engine) as session, pytest.raises(ValueError, match="明示"):
        runtime.segment_reference(session, row, row["region_run_id"], settings, models)
