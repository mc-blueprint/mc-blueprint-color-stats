import copy
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

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
from colorstats.schema.models import (
    Asset,
    Job,
    ProcessingRun,
    ProcessingRunInput,
    Retention,
    Subject,
)
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


def write(queue, asset, source, *, code_version="test", **kwargs):
    payload, gate_id, _ = source
    return privacy.write(queue, asset, gate_id, payload["region_run_id"],
                         code_version=code_version, **kwargs)


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
        privacy.record_hold(queue, asset, rid, code_version="mobile", reviewer="確認者",
                            presented_source_sha256=review_source[2], note="番号返信での問題指摘")
        with pytest.raises(PermissionError, match="失効"):
            execute(queue.engine, selection, tmp_path / "stale", quality=quality,
                    code_version="test")
        from colorstats.stats.aggregate import register

        manifest = json.loads((tmp_path / "snapshot/manifest.json").read_text())
        pending_run = SimpleNamespace(
            stage="aggregate", config_hash="unused", taxonomy_version="0.1.0",
            parameters={"payload": {"snapshot": str(tmp_path / "snapshot")}},
        )
        with Session(queue.engine) as session, pytest.raises(PermissionError, match="失効"):
            register(session, pending_run, {"snapshot_id": manifest["snapshot_id"]})


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


def test_code版の変更でも人の訂正を迂回できない(queue, asset, review_source):
    first = write(queue, asset, review_source)
    sibling = write(queue, asset, review_source, code_version="before-correction")
    human = write(queue, asset, review_source, input_run_id=first, reviewer="確認者",
                  real_people="present", presented_source_sha256=review_source[2], note="人物")
    renewed = write(queue, asset, review_source, code_version="after-correction")
    with Session(queue.engine) as session:
        data = session.get(ProcessingRun, renewed).parameters["evidence"]
        assert data["real_people"] == "present"
        for rid in (first, sibling, human, renewed):
            with pytest.raises(PermissionError):
                privacy.selection(session, asset, rid)
    corrected = write(queue, asset, review_source, input_run_id=human, reviewer="確認者",
                      real_people="absent", presented_source_sha256=review_source[2], note="訂正")
    latest = write(queue, asset, review_source, code_version="after-new-correction")
    with Session(queue.engine) as session:
        assert privacy.selection(session, asset, corrected)
        assert privacy.selection(session, asset, latest)


@pytest.mark.parametrize("retained", [False, True])
def test_hashだけの新契約を旧qualityへ代替しない(queue, asset, review_source, retained):
    rid = write(queue, asset, review_source)
    with Session(queue.engine) as session, session.begin():
        if retained:
            session.add(Retention(asset_id=asset, expires_at=datetime.now(UTC) + timedelta(days=1),
                                  backup_until=datetime.now(UTC) + timedelta(days=2)))
        row = privacy.selection(session, asset, rid)
        payload = {k: v for k, v in row.items() if k.endswith("_hash")}
        with pytest.raises(PermissionError):
            retention.check_privacy(session, asset, payload)


def test_Retentionのある画像は旧qualityの承認だけで採用しない(queue, asset, review_source):
    with Session(queue.engine) as session, session.begin():
        session.add(Retention(asset_id=asset, expires_at=datetime.now(UTC) + timedelta(days=1),
                              backup_until=datetime.now(UTC) + timedelta(days=2)))
        with pytest.raises(PermissionError):
            retention.check_privacy(session, asset, {})


@pytest.mark.parametrize("privacy_written", [False, True])
def test_旧writerは新契約の対象を変更できない(queue, asset, review_source, privacy_written):
    if privacy_written:
        write(queue, asset, review_source)
    with Session(queue.engine) as session, session.begin():
        before = copy.deepcopy(session.get(Asset, asset).quality)
        with pytest.raises(PermissionError):
            retention.review_privacy(session, asset, reviewer="確認者", subject="building",
                                     decision="pending", note="番号返信")
        assert session.get(Asset, asset).quality == before


def test_番号返信の保留は別runに保存され全承認と新版runを失効させる(
    queue, asset, review_source,
):
    first = write(queue, asset, review_source)
    sibling = write(queue, asset, review_source, code_version="sibling")
    held = privacy.record_hold(queue, asset, first, code_version="mobile",
                               reviewer="確認者", presented_source_sha256=review_source[2],
                               note="番号返信での問題指摘")
    renewed = write(queue, asset, review_source, code_version="after-hold")
    with Session(queue.engine) as session:
        assert session.get(ProcessingRun, first).parameters["verdict"]["decision"] == "accepted"
        assert session.get(ProcessingRunInput, (held, first))
        for rid in (first, sibling, held, renewed):
            with pytest.raises(PermissionError):
                privacy.selection(session, asset, rid)
        assert session.get(Asset, asset).quality["privacy_review"]["reviewer"] == "旧確認者"
        assert session.get(ProcessingRun, held).parameters["evidence"]["real_people"] == "absent"
    cleared = write(queue, asset, review_source, input_run_id=held, reviewer="確認者",
                    real_people="absent", presented_source_sha256=review_source[2], note="再確認")
    with Session(queue.engine) as session:
        assert privacy.selection(session, asset, cleared)


def test_issue120番号返信は新privacy契約を失効させ旧writerを使わない(
    queue, asset, review_source, monkeypatch, tmp_path,
):
    from bench.issue114.mobile import apply_privacy_reply, reply_reviews
    from bench.issue114.privacy import digest

    source, gate_id, source_sha256 = review_source
    original = privacy.write(
        queue, asset, gate_id, source["region_run_id"], code_version="test",
    )
    review_rows = [{"asset_id": str(asset), "decision": "accepted", "subject": "building",
                    "reason": "person_not_detected", "person_ratio": 0.0, "mask_ratio": 0.0}]
    manifest = tmp_path / "review-manifest.json"
    manifest.write_text(json.dumps({"required_ids": [str(asset)], "rows": review_rows}))
    mapping = {"format": "issue114-mobile-v1", "decisions_sha256": "a" * 64,
               "review_manifest_sha256": digest(manifest),
               "rows": [review_rows[0] | {"number": 1,
                   "image_gate_run_id": str(gate_id),
                   "region_policy_run_id": str(source["region_run_id"]),
                   "privacy_review_run_id": str(original),
                   "presented_source_sha256": source_sha256,
                   "confirmed_real_people": "absent"}]}
    reply = reply_reviews(mapping, manifest, "a" * 64,
                          "全1枚確認済み\n1: 確認内容の誤り")

    def old_writer(*args, **kwargs):
        raise AssertionError("旧privacy writerを呼び出しました")

    monkeypatch.setattr(retention, "review_privacy", old_writer)
    reply["reviewer"] = "確認者"
    applied = apply_privacy_reply(queue, reply)
    held_id = applied["rows"][0]["recorded_privacy_review_run_id"]

    with Session(queue.engine) as session:
        with pytest.raises(PermissionError, match="失効"):
            privacy.selection(session, asset, original)
        held = session.get(ProcessingRun, held_id)
        assert held.parameters["verdict"] == {"decision": "pending", "reason": "human_hold"}


def test_issue120閲覧検証は保留privacy_runのrun_hashを受け付ける(
    queue, asset, review_source,
):
    from bench.issue114.mobile import validate_presentation_run

    source, gate_id, source_sha256 = review_source
    original = privacy.write(
        queue, asset, gate_id, source["region_run_id"], code_version="test",
    )
    held_id = privacy.record_hold(
        queue, asset, original, code_version="test", reviewer="確認者",
        presented_source_sha256=source_sha256, note="閲覧対象の保留例",
    )

    with Session(queue.engine) as session:
        held = session.get(ProcessingRun, held_id)
        with pytest.raises(PermissionError, match="保留"):
            privacy.selection(session, asset, held_id)
        selection = {"image_gate_run_id": str(gate_id),
                     "region_policy_run_id": str(source["region_run_id"]),
                     "privacy_review_run_id": str(held_id),
                     "privacy_review_hash": digest(held.parameters)}
        assert validate_presentation_run(session, asset, selection) == held
        with pytest.raises(ValueError, match="run/hash"):
            validate_presentation_run(session, asset, selection | {
                "privacy_review_hash": "0" * 64,
            })


@pytest.mark.parametrize("wrong_hash", [False, True])
def test_issue120正規selectionでHTMLを生成しpolicy定義hashへの差替えは拒否する(
    queue, asset, review_source, tmp_path, wrong_hash,
):
    from bench.issue114.mobile import build
    from bench.issue114.privacy import digest as file_digest

    source, _, _ = review_source
    rid = write(queue, asset, review_source)
    with Session(queue.engine) as session, session.begin():
        retention.register_asset(session, session.get(Asset, asset), {}, "test")
        selection = privacy.selection(session, asset, rid)
        policy = region_policy.reference(session.get(ProcessingRun, source["region_run_id"]))
        raw = Path(session.get(Asset, asset).storage_path)
    if wrong_hash:
        selection["region_policy_hash"] = policy["policy_hash"]
    bundle, execution, output = (tmp_path / name for name in ("bundle", "execution", "mobile"))
    (bundle / "images").mkdir(parents=True)
    execution.mkdir()
    with Image.open(raw) as image:
        image.save(bundle / "images" / f"{asset}-raw.png")
    row = {"asset_id": str(asset), "selection": selection,
           "input_path": source["input_path"], "input_sha256": policy["input_sha256"],
           "mask_path": policy["exclusions"]["person"]["path"],
           "mask_sha256": policy["exclusions"]["person"]["sha256"],
           "decision": "accepted", "subject": "building", "reason": "person_not_detected",
           "person_ratio": 0, "mask_ratio": 0}
    decisions = execution / "privacy-decisions.json"
    decisions.write_text(json.dumps([row]))
    (bundle / "manifest.json").write_text(json.dumps({
        "required_ids": [str(asset)], "random_ids": [str(asset)], "boundary_ids": [],
        "decisions_sha256": file_digest(decisions),
    }))
    if wrong_hash:
        with pytest.raises(ValueError, match="参照が一致"):
            build(queue.engine, bundle, execution, output, Path("taxonomy"))
        assert not output.exists()
    else:
        build(queue.engine, bundle, execution, output, Path("taxonomy"))
        assert (output / "review-01.html").exists()
        mapping = json.loads((output / "number-map.json").read_text())
        assert mapping["rows"][0]["privacy_review_run_id"] == str(rid)


@pytest.mark.parametrize("state", [
    "accepted", "corrected_person", "human_hold", "policy_hold", "policy_excluded",
])
def test_issue120問題なし返信は既存の人物訂正と保留を変更しない(
    queue, asset, review_source, state,
):
    from bench.issue114.mobile import apply_privacy_reply

    original = write(queue, asset, review_source)
    if state in {"corrected_person", "human_hold"}:
        original = write(queue, asset, review_source, input_run_id=original, reviewer="確認者",
                         real_people="present" if state == "corrected_person" else "absent",
                         hold=state == "human_hold", presented_source_sha256=review_source[2],
                         note="人物訂正または保留")
    elif state in {"policy_hold", "policy_excluded"}:
        with Session(queue.engine) as session, session.begin():
            gate = session.get(ProcessingRun, review_source[1])
            parameters = copy.deepcopy(gate.parameters)
            path = Path(parameters["result_path"])
            result = json.loads(path.read_text())
            if state == "policy_hold":
                result["result"]["real_people"] = "uncertain"
            else:
                result["result"]["black_and_white"] = True
            path.write_text(json.dumps(result))
            parameters["result_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            parameters["verdict"] = image_gate.decision(result["result"])
            gate.parameters = parameters
        original = write(queue, asset, review_source, code_version="uncertain")
    with Session(queue.engine) as session:
        before = copy.deepcopy(session.get(ProcessingRun, original).parameters)
    data = {"reviewer": "ユーザー", "rows": [{
        "asset_id": str(asset), "error_found": False, "note": "提示画像を確認済み・問題なし",
        "privacy_review_run_id": str(original), "presented_source_sha256": review_source[2],
        "image_gate_run_id": str(review_source[1]),
        "region_policy_run_id": str(review_source[0]["region_run_id"]),
        "confirmed_real_people": "absent",
    }]}
    applied = apply_privacy_reply(queue, data)
    with Session(queue.engine) as session:
        recorded = session.get(ProcessingRun, applied["rows"][0]["recorded_privacy_review_run_id"])
        assert recorded.parameters["evidence"] == before["evidence"]
        assert recorded.parameters["verdict"] == before["verdict"]
        assert session.get(ProcessingRunInput, (recorded.id, original))
        if state != "accepted":
            with pytest.raises(PermissionError):
                privacy.selection(session, asset, recorded.id)


def test_訂正前に準備したjobも完了時に承認を迂回できない(
    queue, asset, review_source, monkeypatch,
):
    first = write(queue, asset, review_source)
    with monkeypatch.context() as context:
        context.setattr(queue, "claim", lambda *a, **kw: None)
        with pytest.raises(RuntimeError):
            write(queue, asset, review_source, code_version="queued")
    privacy.record_hold(queue, asset, first, code_version="mobile", reviewer="確認者",
                        presented_source_sha256=review_source[2], note="保留")
    claim = queue.claim(("review",))
    prepared = privacy.prepare(claim)
    with pytest.raises(PermissionError, match="失効"):
        queue.complete(claim, prepared.info,
                       lambda s, r: privacy.register(s, r, prepared.data))


def test_同じ実入力のAとBを別runへ作り直しても人の訂正を継承する(
    queue, asset, review_source,
):
    first = write(queue, asset, review_source)
    privacy.record_hold(queue, asset, first, code_version="mobile", reviewer="確認者",
                        presented_source_sha256=review_source[2], note="保留")

    def clone(run_id):
        with Session(queue.engine) as session:
            old = session.get(ProcessingRun, run_id)
            stage = old.stage
            parameters, paths = copy.deepcopy(old.parameters), dict(old.output_paths)
        job_id = queue.enqueue(stage, asset, digest({"clone": str(run_id)}), {"clone": str(run_id)})
        claim = queue.claim((stage,), job_ids=[job_id])

        def register(session, run):
            run.output_paths = paths

        return queue.complete(claim, RunInfo("open", "test", "0.1.0", "fixture", parameters),
                              register)

    gate_id, segment_id = clone(review_source[1]), clone(review_source[0]["region_run_id"])
    renewed = privacy.write(queue, asset, gate_id, segment_id, code_version="new-runs")
    with Session(queue.engine) as session, pytest.raises(PermissionError, match="保留"):
        privacy.selection(session, asset, renewed)
