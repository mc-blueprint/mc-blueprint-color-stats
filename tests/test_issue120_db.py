"""現行A/B/C契約から提示・番号返信・共有保持までを隔離DBで検証する。"""

import copy
import json
import os
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from bench.issue114 import mobile
from bench.issue114.privacy import digest, save
from sqlalchemy import select
from sqlalchemy.orm import Session

from colorstats import privacy_review, retention
from colorstats.api_budget import digest as contract_digest
from colorstats.schema.models import (
    Asset,
    ProcessingRun,
    ProcessingRunInput,
    Retention,
    RetentionFile,
)
from tests.test_issue114_mobile_retention import shared_mobile as shared_mobile
from tests.test_privacy_review_db import review_source as review_source
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue
from tests.test_region_policy import regional_payload as regional_payload
from tests.test_region_policy_db import policy_source as policy_source
from tests.test_retention import managed as managed
from tests.test_segment import payload as payload
from tests.test_segment_db import prep_source as prep_source

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="隔離DB専用")


@pytest.fixture
def presentation(queue, asset, review_source, tmp_path, request):
    source, gate, source_sha = review_source
    rid = privacy_review.write(queue, asset, gate, source["region_run_id"], code_version="test")
    with Session(queue.engine) as session, session.begin():
        retention.register_asset(session, session.get(Asset, asset), {}, "test")
        selection = privacy_review.selection(session, asset, rid)
    state = getattr(request, "param", "accepted")
    if state != "accepted":
        rid = privacy_review.write(
            queue, asset, gate, source["region_run_id"], code_version="test", input_run_id=rid,
            reviewer="ユーザー", real_people="present" if state == "person" else "absent",
            hold=state == "hold", presented_source_sha256=source_sha, note="合成人物根拠",
        )
        with Session(queue.engine) as session:
            selection.update(privacy_review_run_id=str(rid), privacy_review_hash=contract_digest(
                session.get(ProcessingRun, rid).parameters))
    policy = source["region_policy"]
    row = {"asset_id": str(asset), "selection": selection,
           "input_path": source["input_path"], "input_sha256": policy["input_sha256"],
           "mask_path": policy["exclusions"]["person"]["path"],
           "mask_sha256": policy["exclusions"]["person"]["sha256"],
           "decision": "accepted", "subject": "building", "reason": "person_not_detected",
           "person_ratio": 0.0, "mask_ratio": 0.0}
    bundle, execution = tmp_path / "bundle", tmp_path / "execution"
    bundle.mkdir()
    execution.mkdir()
    save(execution / "privacy-decisions.json", [row])
    manifest = {"required_ids": [str(asset)], "random_ids": [str(asset)], "boundary_ids": [],
                "population": 10, "decisions_sha256": digest(execution / "privacy-decisions.json"),
                "rows": [{k: v for k, v in row.items() if k in {
                    "asset_id", "input_sha256", "decision", "subject", "reason",
                    "person_ratio", "mask_ratio"}}]}
    save(bundle / "manifest.json", manifest)
    save(execution / "review-manifest.json", manifest)
    return bundle, execution, tmp_path / "mobile", rid


@pytest.mark.parametrize("view", ["raw", "comparison"])
def test_固定原画像と版を提示し予測比較を区別する(queue, asset, presentation, view):
    bundle, execution, output, rid = presentation
    mobile.build(queue.engine, bundle, execution, output, Path("taxonomy"), view=view)
    mapping = json.loads((output / "number-map.json").read_text())
    mobile.validate_delivery(mapping, output)
    content = (output / "review-01.html").read_text()
    assert mapping["groups"] == {"population": 10, "random": 1, "challenge": 0,
                                 "sample_items": 1, "nonpresented_holds": 0}
    assert mapping["rows"][0]["view"] == view
    assert mapping["rows"][0]["privacy_policy_version"] == "privacy-review-v2"
    if view == "raw":
        assert "もとの写真だけの確認" in content
        assert "privacy-review-v2" not in content and 'class="mask-comparison"' not in content
        assert "人物：" not in content and "これまでの判断：" not in content
    else:
        assert "比較する確認" in content and "privacy-review-v2" in content
        assert 'class="mask-comparison"' in content
    with Session(queue.engine) as session:
        assert mapping["rows"][0]["presented_source_sha256"] == session.get(Asset, asset).sha256
        evidence = session.get(ProcessingRun, rid).parameters["evidence"]
        assert evidence["policy"]["mask_rescue"] is False


@pytest.mark.parametrize("presentation", ["accepted", "hold", "person"], indirect=True)
@pytest.mark.parametrize("problem", [False, True])
def test_提示画像だけを追記確認し保留と人物方針を解除しない(
        queue, asset, presentation, problem):
    bundle, execution, output, rid = presentation
    mobile.build(queue.engine, bundle, execution, output, Path("taxonomy"))
    mapping = json.loads((output / "number-map.json").read_text())
    with Session(queue.engine) as session:
        before = copy.deepcopy(session.get(ProcessingRun, rid).parameters)
        quality = copy.deepcopy(session.get(Asset, asset).quality)
    reply = mobile.reply_reviews(
        mapping, execution / "review-manifest.json", digest(execution / "privacy-decisions.json"),
        "全1枚確認済み\n" + ("1: 人物の見落とし" if problem else "問題なし"), directory=output,
    )
    result = mobile.apply_privacy_reply(queue, reply)
    new_id = UUID(result["rows"][0]["recorded_privacy_review_run_id"])
    with Session(queue.engine) as session:
        after = session.get(ProcessingRun, new_id).parameters
        assert after["reviewer"] == "ユーザー"
        assert session.get(ProcessingRun, rid).parameters == before
        assert session.get(Asset, asset).quality == quality
        assert session.get(ProcessingRunInput, (new_id, rid))
        assert after["evidence"]["real_people"] == before["evidence"]["real_people"]
        assert after["evidence"]["human_hold"] == (problem or before["evidence"]["human_hold"])
        with pytest.raises(PermissionError):
            privacy_review.selection(session, asset, rid)
        if problem or before["verdict"]["decision"] == "pending":
            with pytest.raises(PermissionError):
                privacy_review.selection(session, asset, new_id)


@pytest.mark.parametrize("change", ["html", "input", "manifest", "number", "reply"])
def test_提示物と固定対象が変わった返信は取り込まない(queue, presentation, change):
    bundle, execution, output, _ = presentation
    mobile.build(queue.engine, bundle, execution, output, Path("taxonomy"))
    mapping = json.loads((output / "number-map.json").read_text())
    manifest = execution / "review-manifest.json"
    reply = "全1枚確認済み\n問題なし"
    if change == "html":
        with (output / "review-01.html").open("a") as stream:
            stream.write("changed")
    elif change == "input":
        mapping["rows"][0]["input_sha256"] = "0" * 64
    elif change == "manifest":
        with manifest.open("a") as stream:
            stream.write(" ")
    elif change == "number":
        mapping["rows"][0]["number"] = 2
    else:
        reply = "全1枚未確認\n問題なし"
    with pytest.raises(ValueError):
        mobile.reply_reviews(mapping, manifest, digest(execution / "privacy-decisions.json"),
                             reply, directory=output)


def test_共有HTMLとtarと番号表も保持登録し失効で削除する(queue, asset, presentation, tmp_path):
    bundle, execution, output, _ = presentation
    mobile.build(queue.engine, bundle, execution, output, Path("taxonomy"), host="local-test")
    shared = tmp_path / "shared"
    mobile.share(queue.engine, output, shared, host="local-test")
    with tarfile.open(shared / "review.tar") as archive:
        assert archive.getnames() == ["review-01.html"]
        assert archive.extractfile("review-01.html").read() == (
            output / "review-01.html").read_bytes()
    with Session(queue.engine) as session, session.begin():
        files = list(session.scalars(select(RetentionFile).where(RetentionFile.asset_id == asset)))
        assert {Path(f.path).name for f in files if Path(f.path).parent == shared} == {
            "review-01.html", "number-map.json", "review.tar"}
        assert all(f.kind == "image_bundle" for f in files if Path(f.path).parent == shared)
        session.scalar(select(Retention).where(Retention.asset_id == asset)).expires_at = (
            datetime.now(UTC) - timedelta(seconds=1))
    with Session(queue.engine) as session, session.begin():
        retention.cleanup(session, host="local-test")
    assert not list(shared.iterdir()) and not list(output.iterdir())


def test_共有時に失効した画像を再配布しない(queue, asset, presentation, tmp_path):
    bundle, execution, output, _ = presentation
    mobile.build(queue.engine, bundle, execution, output, Path("taxonomy"))
    with Session(queue.engine) as session, session.begin():
        session.scalar(select(Retention).where(Retention.asset_id == asset)).stopped_at = (
            datetime.now(UTC))
    shared = tmp_path / "shared"
    with pytest.raises(PermissionError):
        mobile.share(queue.engine, output, shared)
    assert not shared.exists()


@pytest.mark.parametrize("change", ["source", "mask", "policy", "correction"])
def test_提示前に根拠が変わった対象は出力しない(
        queue, asset, presentation, change, monkeypatch):
    bundle, execution, output, rid = presentation
    if change == "source":
        with Session(queue.engine) as session:
            path = Path(session.get(Asset, asset).storage_path)
        with path.open("ab") as stream:
            stream.write(b"changed")
    elif change == "mask":
        path = execution / "privacy-decisions.json"
        rows = json.loads(path.read_text())
        rows[0]["mask_sha256"] = "0" * 64
        path.unlink()
        save(path, rows)
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["decisions_sha256"] = digest(path)
        manifest_path.unlink()
        save(manifest_path, manifest)
    elif change == "policy":
        monkeypatch.setattr(privacy_review, "POLICY", {**privacy_review.POLICY, "version": "old"})
    else:
        with Session(queue.engine) as session:
            sha = session.get(Asset, asset).sha256
        privacy_review.record_hold(queue, asset, rid, code_version="test", reviewer="ユーザー",
                                   presented_source_sha256=sha, note="提示前の訂正")
    with pytest.raises((ValueError, PermissionError)):
        mobile.build(queue.engine, bundle, execution, output, Path("taxonomy"))
    assert not output.exists()


def test_標本群を重複せず群ごとに表示し母数と件数を保持する(queue, shared_mobile):
    bundle, execution, output, _, _ = shared_mobile
    path = bundle / "manifest.json"
    manifest = json.loads(path.read_text())
    ids = sorted(manifest["required_ids"])
    manifest.update(random_ids=[ids[-1]], boundary_ids=ids, population=20)
    decisions = json.loads((execution / "privacy-decisions.json").read_text())
    manifest["rows"] = [{k: row[k] for k in ("asset_id", "decision", "subject", "reason",
                                            "person_ratio", "mask_ratio")} for row in decisions]
    path.write_text(json.dumps(manifest))
    (execution / "review-manifest.json").write_bytes(path.read_bytes())
    mobile.build(queue.engine, bundle, execution, output, Path("taxonomy"), require_contracts=False)
    mapping = json.loads((output / "number-map.json").read_text())
    assert mapping["groups"] == {"population": 20, "random": 1, "challenge": 1,
                                 "sample_items": 2, "nonpresented_holds": 0}
    assert [r["asset_id"] for r in mapping["rows"]] == list(reversed(ids))
    assert [r["number"] for r in mapping["rows"]] == [1, 2]
    assert "無作為群から重複除外" in mapping["rows"][0]["groups"]
    assert mapping["rows"][1]["groups"] == ["目的抽出challenge群"]
    reply = mobile.reply_reviews(mapping, execution / "review-manifest.json",
                                 digest(execution / "privacy-decisions.json"),
                                 "全2枚確認済み\n問題なし", directory=output)
    assert [r["asset_id"] for r in reply["rows"]] == list(reversed(ids))


def test_別assetでも同じ取得画像を重複して提示しない(queue, shared_mobile):
    bundle, execution, output, _, _ = shared_mobile
    paths = list((bundle / "images").glob("*-raw.png"))
    paths[1].write_bytes(paths[0].read_bytes())
    mobile.build(queue.engine, bundle, execution, output, Path("taxonomy"),
                 require_contracts=False)
    mapping = json.loads((output / "number-map.json").read_text())
    assert [r["number"] for r in mapping["rows"]] == [1, 1]
    assert (output / "review-01.html").read_text().count('class="raw"') == 1
    mobile.validate_delivery(mapping, output)


def test_同一SHAでも取得byteが異なればまとめない(queue, shared_mobile, monkeypatch):
    bundle, execution, output, _, _ = shared_mobile
    monkeypatch.setattr(mobile, "_uri_sha", lambda uri: "a" * 64)
    with pytest.raises(ValueError, match="byte"):
        mobile.build(queue.engine, bundle, execution, output, Path("taxonomy"),
                     require_contracts=False)


def test_保持登録に失敗した共有コピーだけを取り除く(queue, presentation, tmp_path, monkeypatch):
    bundle, execution, output, _ = presentation
    mobile.build(queue.engine, bundle, execution, output, Path("taxonomy"))
    original = {p.name: p.read_bytes() for p in output.iterdir()}

    def fail(*args, **kwargs):
        raise RuntimeError("保持登録の失敗")

    monkeypatch.setattr(retention, "register_file", fail)
    shared = tmp_path / "shared"
    with pytest.raises(RuntimeError, match="保持登録"):
        mobile.share(queue.engine, output, shared)
    assert not shared.exists()
    assert {p.name: p.read_bytes() for p in output.iterdir()} == original
