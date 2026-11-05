import copy
import hashlib
import io
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from colorstats.collect import Candidate, SearchRequest, quality, stage
from colorstats.schema.models import Asset, Job, ProcessingRun
from tests.test_collect import (
    Response,
    adapter_for,
    claim_for,
    isolated_acquisition_check,  # noqa: F401
    payload_for,
    policy,  # noqa: F401
)
from tests.test_collect_rendition import recorded_thumbnail
from tests.test_queue import database, queue  # noqa: F401


def test_既定はCommons縮小で他ソースは既存の取得方式():
    assert SearchRequest("wikimedia_commons", "castle").download_mode == "thumbnail"
    for provider in ("openverse", "loc", "mapillary"):
        assert SearchRequest(provider, "castle").download_mode == "original"
    assert SearchRequest("wikimedia_commons", "castle", download_mode="original").download_mode == (
        "original"
    )


@pytest.mark.parametrize("mode", ["original", "thumbnail"])
@pytest.mark.parametrize("edge", [1, 1279, 1280])
def test_原本と縮小の受信実寸へ最低解像度を適用する(
    policy, tmp_path, monkeypatch, mode, edge,  # noqa: F811
):
    image = io.BytesIO()
    Image.new("RGB", (edge, 800), "blue").save(image, "PNG")
    content = image.getvalue()
    recorded = recorded_thumbnail(width=3000, height=2000)
    if mode == "original":
        recorded[1]["query"]["pages"][0]["imageinfo"][0].update(width=edge, height=800)
    recorded[1]["query"]["pages"][0]["imageinfo"][0]["sha1"] = hashlib.sha1(content).hexdigest()
    adapter, calls = adapter_for(policy, [Response(r) for r in recorded] + [Response(content)])
    monkeypatch.setattr(stage, "CommonsAdapter", lambda policy: adapter)
    monkeypatch.setattr(stage, "existing_rendition", lambda *args: None)
    payload, digest = payload_for(tmp_path)
    payload.update(quality_policy=copy.deepcopy(quality.QUALITY_POLICY))
    payload["request"]["download_mode"] = mode
    prepared = stage.prepare(claim_for(payload, digest))
    assert len(calls) == 3
    if edge < 1280:
        assert not prepared.files
        assert prepared.info.parameters["skipped"][0]["reason"] == "below_min_resolution"
    else:
        assert prepared.data["records"][0]["received"]["width"] == edge


def test_縦長も幅と高さを1280以内でAPIへ要求する(policy):  # noqa: F811
    from urllib.parse import parse_qs, urlsplit

    recorded = recorded_thumbnail(width=1000, height=2000)
    adapter, calls = adapter_for(policy, [Response(r) for r in recorded])
    candidate = adapter.search(SearchRequest("wikimedia_commons", "castle")).candidates[0]
    parameters = parse_qs(urlsplit(calls[1][0].full_url).query)
    assert parameters["iiurlwidth"] == parameters["iiurlheight"] == ["1280"]
    assert candidate.exclusion_reason is None


@pytest.mark.parametrize("case,reason", [
    ("small_mismatch", "original_dimensions_mismatch"),
    ("large_mismatch", "original_dimensions_mismatch"),
    ("small", "below_min_resolution"),
    ("image_limit", "received_header_image_limit"),
    ("unreadable", "received_header_unreadable"),
])
def test_原本ヘッダーだけで候補を除外し先行取得を保持して次へ進む(
    policy, tmp_path, monkeypatch, case, reason,  # noqa: F811
):
    from dataclasses import asdict

    def content(size):
        image = io.BytesIO()
        Image.new("RGB", size, "blue").save(image, "PNG")
        return image.getvalue()

    good = content((1600, 1000))
    size = {
        "small_mismatch": (800, 600), "large_mismatch": (1600, 1000),
        "small": (800, 600), "image_limit": (2400, 1600), "unreadable": (3000, 2000),
    }[case]
    bad = b"not an image" if case == "unreadable" else content(size)
    recorded = recorded_thumbnail()
    adapter, _ = adapter_for(policy, [Response(r) for r in recorded])
    result = adapter.search(SearchRequest("wikimedia_commons", "castle", download_mode="original"))
    base = asdict(result.candidates[0])
    candidates = []
    for rank, data in enumerate((good, bad, good)):
        width, height = size if rank == 1 else (1600, 1000)
        if rank == 1 and case.endswith("mismatch"):
            width, height = 3000, 2000
        candidates.append(Candidate(**{
            **base, "rank": rank, "source_url": base["source_url"] + f"/{rank}",
            "original_url": base["original_url"].partition("?")[0] + f"?rank={rank}",
            "width": width, "height": height,
            "rendition": {**base["rendition"], "native_id": str(rank), "original": {
                **base["rendition"]["original"], "width": width, "height": height,
                "sha1": hashlib.sha1(data).hexdigest(),
            }},
        }))
    monkeypatch.setattr(adapter, "search", lambda request: replace(result, candidates=candidates))
    monkeypatch.setattr(adapter, "download", lambda candidate, path: path.write_bytes(
        (good, bad, good)[candidate.rank],
    ))
    monkeypatch.setattr(stage, "CommonsAdapter", lambda policy: adapter)
    monkeypatch.setattr(stage, "existing_rendition", lambda *args: None)
    Image.init()
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1_600_000)
    monkeypatch.setattr(Image.Image, "load", lambda *args, **kwargs: pytest.fail("画素展開は禁止"))
    payload, digest = payload_for(tmp_path)
    payload["quality_policy"] = quality.QUALITY_POLICY
    discarded, events = [], []
    prepared = stage.prepare(
        claim_for(payload, digest), discard=lambda request, candidate: discarded.append(candidate),
        observer=lambda event, value: events.append((event, value)),
    )
    assert [record["candidate"]["rank"] for record in prepared.data["records"]] == [0, 2]
    assert discarded == [candidates[1]]
    assert prepared.info.parameters["skipped"][0]["reason"] == reason
    assert [entry["rank"] for entry in prepared.info.parameters["skipped"]] == [1]
    assert sum(value for event, value in events if event == "downloads") == 3
    assert {path for path, _ in prepared.files} == set((tmp_path / "raw").rglob("*.tmp"))
    assert all(path.read_bytes() == good for path, _ in prepared.files)


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="隔離PostgreSQL")
@pytest.mark.parametrize("resolved", [False, True])
def test_フラグ原本jobの取得と再判定は既存assetとrunを変更しない(
    queue, policy, tmp_path, monkeypatch, resolved,  # noqa: F811
):
    image = io.BytesIO()
    Image.new("RGB", (1600, 1000), "blue").save(image, "PNG")
    content = image.getvalue()
    original_content = content
    if resolved:
        import numpy as np

        original = io.BytesIO()
        Image.fromarray(np.random.default_rng(0).integers(
            0, 256, (1600, 1280, 3), dtype=np.uint8,
        )).save(original, "PNG")
        original_content = original.getvalue()
    recorded = recorded_thumbnail(width=1280 if resolved else 1600,
                                  height=1600 if resolved else 1000)
    recorded[1]["query"]["pages"][0]["imageinfo"][0]["sha1"] = hashlib.sha1(
        original_content,
    ).hexdigest()
    adapter, calls = adapter_for(policy, [Response(r) for r in recorded] + [Response(content)])
    monkeypatch.setattr(stage, "CommonsAdapter", lambda policy: adapter)
    payload, _ = payload_for(tmp_path)
    payload.update(quality_policy=copy.deepcopy(quality.QUALITY_POLICY))
    payload["request"]["download_mode"] = "thumbnail"
    queue.enqueue("collect", None, "a" * 64, payload)
    claim = queue.claim(["collect"])
    prepared = stage.prepare(claim)
    assert prepared.data["records"][0]["quality"]["blur_suspected"]
    run_id = queue.complete(claim, prepared.info, lambda session, run: stage.register(
        session, run, prepared.data,
    ), prepared.files)
    with Session(queue.engine) as session:
        asset = session.scalars(select(Asset)).one()
        before = copy.deepcopy(asset.quality)
        sha, path = asset.sha256, asset.storage_path
        collect = copy.deepcopy(session.get(ProcessingRun, run_id).parameters)
        job = session.scalars(select(Job).where(Job.stage == "review")).one()
        assert job.payload["original_review"]["reasons"] == ["blur_suspected"]
        assert job.payload["original_review"]["from_variant"]["variant"] == "thumbnail"
    adapter, original_calls = adapter_for(policy, [Response(original_content)])
    monkeypatch.setattr(stage, "CommonsAdapter", lambda policy: adapter)
    claim = queue.claim(["review"])
    prepared = quality.prepare(claim)
    assert len(original_calls) == 1
    assert original_calls[0][0].full_url == claim.payload["original_review"]["candidate"][
        "original_url"
    ]
    review_id = queue.complete(claim, prepared.info, lambda session, run: quality.register(
        session, run, prepared.data,
    ), prepared.files)
    with Session(queue.engine) as session:
        assert session.scalar(select(func.count()).select_from(Asset)) == 1
        current = session.scalars(select(Asset)).one()
        assert (current.quality, current.sha256, current.storage_path) == (before, sha, path)
        assert session.get(ProcessingRun, run_id).parameters == collect
        result = session.get(ProcessingRun, review_id).parameters["original_results"][0]
        assert result["decision"] == ("accepted" if resolved else "rejected")
        assert Path(result["path"]).read_bytes() == original_content
    assert len(calls) == 3


@pytest.mark.parametrize("distance,intersection,status", [
    (0.02, 85, "passed"), (0.020001, 85, "warning"), (0.02, 84, "warning"),
])
def test_許容差の境界と警告を記録する(distance, intersection, status, caplog):
    result = quality.audit([{"comparison": {
        "dominant_oklab_distance": distance,
        "mask_agreement": {"wall": {"group": "major", "intersection": intersection, "union": 100}},
    }}, {"status": "below_min_resolution"}])
    assert result["status"] == status
    assert (result["evaluated"], result["unevaluated"]) == (1, 1)
    assert ("許容差超過" in caplog.text) == (status == "warning")
    assert quality.audit([])["status"] == "unevaluated"


def test_監査は画素加重と平均を使い固定入力の改変を拒否する(tmp_path):
    rows = [
        {"comparison": {"dominant_oklab_distance": distance, "mask_agreement": {
            "wall": {"group": "major", "intersection": intersection, "union": union},
        }}}
        for distance, intersection, union in [(0.01, 1, 1), (0.03, 84, 99)]
    ]
    source, output = tmp_path / "comparison.json", tmp_path / "audit.json"
    source.write_text(json.dumps(rows), encoding="utf-8")

    class Recorder:
        def enqueue(self, stage, asset, digest, payload):
            self.payload, self.digest = payload, digest

    recorder = Recorder()
    quality.enqueue_audit(recorder, source, output, code_version="test")
    claim = replace(claim_for(recorder.payload, recorder.digest), stage="review")
    prepared = quality.prepare(claim)
    assert prepared.info.parameters["audit"]["major_agreement"] == 0.85
    assert prepared.info.parameters["audit"]["dominant_oklab_mean"] == 0.02
    source.write_text("[]")
    with pytest.raises(ValueError, match="比較入力"):
        quality.prepare(claim)


def test_フラグなしと原本からは再取得jobを予約しない():
    class Never:
        def scalar(self, *args):
            pytest.fail("jobを予約してはいけません")

    candidate = {"rendition": {"variant": "thumbnail"}}
    quality.schedule_original(Never(), None, None, {
        "candidate": candidate, "quality": dict.fromkeys(
            quality.QUALITY_POLICY["original_review_flags"], False,
        ),
    }, {"quality_policy": quality.QUALITY_POLICY})
    candidate["rendition"]["variant"] = "original"
    quality.schedule_original(Never(), None, None, {"candidate": candidate}, {
        "quality_policy": quality.QUALITY_POLICY,
    })


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="隔離PostgreSQL")
def test_原本再判定も既存の測定通信枠を消費し枠超過では取得しない(
    queue, policy, tmp_path, monkeypatch,  # noqa: F811
):
    from dataclasses import asdict

    from colorstats.collect.measurement import Meter

    adapter, _ = adapter_for(policy, [Response(r) for r in recorded_thumbnail()])
    candidate = adapter.search(SearchRequest(
        "wikimedia_commons", "castle", download_mode="original",
    )).candidates[0]
    payload, _ = payload_for(tmp_path)
    payload.update(
        original_review={"candidate": asdict(candidate), "reasons": ["blur_suspected"]},
        quality_policy=quality.QUALITY_POLICY,
        bias={"measurement": {"id": "quality-budget", "api_requests_per_stratum": 10,
                              "http_requests_per_stratum": 1}},
    )
    queue.enqueue("review", None, "f" * 64, payload)
    claim = queue.claim(["review"])
    meter = Meter(queue, claim)
    meter.observe("request")
    meter.finish("stopped")
    adapter, calls = adapter_for(policy, [])
    monkeypatch.setattr(stage, "CommonsAdapter", lambda policy: adapter)
    prepared = quality.prepare(claim)
    assert not calls and not prepared.files
    assert prepared.info.parameters["stop_reason"] == "http_limit"


def test_原本再判定のヘッダー上限は理由付き未評価として一時ファイルを除外する(
    policy, tmp_path, monkeypatch,  # noqa: F811
):
    from dataclasses import asdict

    image = io.BytesIO()
    Image.new("RGB", (1600, 1000), "blue").save(image, "PNG")
    content = image.getvalue()
    recorded = recorded_thumbnail()
    recorded[1]["query"]["pages"][0]["imageinfo"][0]["sha1"] = hashlib.sha1(content).hexdigest()
    adapter, _ = adapter_for(policy, [Response(r) for r in recorded])
    candidate = adapter.search(SearchRequest(
        "wikimedia_commons", "castle", download_mode="original",
    )).candidates[0]
    adapter, calls = adapter_for(policy, [Response(content)])
    monkeypatch.setattr(stage, "CommonsAdapter", lambda policy: adapter)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    payload, digest = payload_for(tmp_path)
    payload.update(original_review={"candidate": asdict(candidate)},
                   quality_policy=quality.QUALITY_POLICY)
    prepared = quality.prepare(claim_for(payload, digest))
    assert len(calls) == 1 and not prepared.files and not prepared.data["records"]
    assert prepared.info.parameters["skipped"][0]["reason"] == "received_header_image_limit"
    assert not list((tmp_path / "raw").rglob("*.tmp"))


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="隔離PostgreSQL")
def test_監査警告を新規runと不変出力へ確定できる(queue, tmp_path):  # noqa: F811
    source = tmp_path / "comparison.json"
    source.write_text(json.dumps([{"comparison": {
        "dominant_oklab_distance": 0.03,
        "mask_agreement": {"wall": {"group": "major", "intersection": 8, "union": 10}},
    }}]))
    job_id = quality.enqueue_audit(queue, source, tmp_path / "audit.json", code_version="test")
    claim = queue.claim(["review"], job_ids=[job_id])
    prepared = quality.prepare(claim)
    run_id = queue.complete(claim, prepared.info, lambda session, run: quality.register(
        session, run, prepared.data,
    ), prepared.files)
    with Session(queue.engine) as session:
        run = session.get(ProcessingRun, run_id)
        result = json.loads(Path(next(iter(run.output_paths.values()))).read_text())
        assert run.parameters["audit"] == result
        assert result["violations"] == ["dominant_oklab_mean", "major_agreement"]
        assert session.scalar(select(func.count()).select_from(Asset)) == 0
