import copy
import hashlib
import io
import json
import os
from dataclasses import asdict, replace
from http.client import HTTPResponse
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from colorstats.collect import SearchRequest
from colorstats.collect.http import _CountingResponse
from colorstats.collect.stage import register
from colorstats.schema.models import Asset, ProcessingRun
from tests.test_collect import (
    RECORDED,
    Response,
    adapter_for,
    claim_for,
    isolated_acquisition_check,  # noqa: F401
    payload_for,
    policy,  # noqa: F401
)
from tests.test_queue import database, queue  # noqa: F401


def test_chunkedなAPI応答を長さ未指定で読み終端をJSONへ混ぜない():
    class Socket:
        def makefile(self, *args):
            return io.BytesIO(
                b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n'
                b'7\r\n{"a":1}\r\n0\r\n\r\n'
            )

    response = HTTPResponse(Socket())
    response.begin()
    counted = _CountingResponse(response, lambda: 0)
    assert json.load(counted) == {"a": 1}
    assert counted.bytes == 7


def test_原本と縮小の別hostでも同じmedia帯域窓を使う(policy, tmp_path):  # noqa: F811
    adapter, calls = adapter_for(policy, [Response(b"x" * 20_000_000) for _ in range(2)])
    events = []
    adapter.observer = lambda event, value=1: events.append((event, value))
    adapter._get("https://upload.wikimedia.org/original.jpg", target=tmp_path / "original")
    adapter._get("https://thumb.wikimedia.org/1280px-test.jpg", target=tmp_path / "thumb")
    assert len(calls) == 2
    assert sum(value for event, value in events if event == "bandwidth_wait_seconds") >= 9
    assert {value["host"] for event, value in events if event == "media_transfer"} == {
        "upload.wikimedia.org", "thumb.wikimedia.org",
    }


def recorded_thumbnail(**updates):
    recorded = copy.deepcopy(RECORDED)
    recorded[1]["query"]["pages"][0]["imageinfo"][0].update(
        timestamp="2026-11-01T00:00:00Z", sha1="a" * 40,
        thumburl="https://upload.wikimedia.org/thumb/1280px-test.jpg",
        thumbwidth=1280, thumbheight=2400, thumbmime="image/jpeg", **updates,
    )
    return recorded


def test_幅1280の縦長画像と原本の契約を分ける(policy, tmp_path):  # noqa: F811
    recorded = recorded_thumbnail(width=3000, height=5625)
    adapter, calls = adapter_for(policy, [Response(r) for r in recorded] + [Response(b"thumb")])
    candidate = adapter.search(SearchRequest(
        "wikimedia_commons", "castle", download_mode="thumbnail",
    )).candidates[0]
    assert candidate.width == 3000 and candidate.height == 5625
    assert candidate.rendition["height"] == 2400
    assert candidate.rendition["original"]["sha256"] is None
    assert candidate.rendition["original"]["sha1"] == "a" * 40
    assert candidate.rendition["revision"] == "2026-11-01T00:00:00Z"
    assert parse_qs(urlsplit(calls[1][0].full_url).query)["iiurlwidth"] == ["1280"]
    assert "thumbmime" in parse_qs(urlsplit(calls[1][0].full_url).query)["iiprop"][0].split("|")
    adapter.download(candidate, tmp_path / "thumb")
    assert calls[-1][0].full_url == candidate.download_url != candidate.original_url


@pytest.mark.parametrize("change,reason", [
    ({"width": 800}, "thumbnail_not_smaller"),
    ({"thumburl": None}, "thumbnail_missing"),
    ({"thumbmime": None}, "thumbnail_missing"),
    ({"timestamp": None}, "thumbnail_revision_missing"),
])
def test_縮小が成立しない候補を明示除外し原本へ戻らない(policy, tmp_path, change, reason):  # noqa: F811
    recorded = recorded_thumbnail()
    recorded[1]["query"]["pages"][0]["imageinfo"][0].update(change)
    adapter, calls = adapter_for(policy, [Response(r) for r in recorded])
    candidate = adapter.search(SearchRequest(
        "wikimedia_commons", "castle", download_mode="thumbnail",
    )).candidates[0]
    assert candidate.exclusion_reason == reason
    with pytest.raises(ValueError, match=reason):
        adapter.download(candidate, tmp_path / "never")
    assert len(calls) == 2


def test_取得モードでjobのハッシュが変わり既定は原本(tmp_path):
    payload, before = payload_for(tmp_path)
    assert payload["request"]["download_mode"] == "original"
    with pytest.raises(ValueError):
        replace(SearchRequest("openverse", "castle"), download_mode="thumbnail")
    from colorstats.collect.stage import enqueue_collect

    class Queue:
        def enqueue(self, stage, asset, digest, payload):
            return digest

    after = enqueue_collect(
        Queue(), SearchRequest("wikimedia_commons", "castle", download_mode="thumbnail"),
        policy_path=Path(__file__).parents[1] / "configs/source_policy.yaml",
        storage_config=Path(payload["storage_config"]), host="windows",
        domain="real_building", code_version="test", taxonomy_version="0.1.0",
    )
    assert after != before


def test_受信PNGの寸法とMIMEを原本JPEGの値から分離する(
    policy, tmp_path, monkeypatch,  # noqa: F811
):
    from PIL import Image

    from colorstats.collect.stage import prepare

    payload, digest = payload_for(tmp_path)
    payload["request"]["download_mode"] = "thumbnail"
    recorded = recorded_thumbnail(width=3000, height=5625)
    image = io.BytesIO()
    Image.new("RGB", (640, 1200), "blue").save(image, format="PNG")
    adapter, _ = adapter_for(policy, [Response(r) for r in recorded] + [Response(image.getvalue())])
    monkeypatch.setattr("colorstats.collect.stage.CommonsAdapter", lambda policy: adapter)
    monkeypatch.setattr("colorstats.collect.stage.existing_rendition", lambda *args: None)
    prepared = prepare(claim_for(payload, digest))
    record = prepared.data["records"][0]
    assert record["received"] == {"width": 640, "height": 1200, "mime": "image/png"}
    assert record["candidate"]["rendition"]["original"]["width"] == 3000
    assert record["sha256"] != record["candidate"]["rendition"]["original"]["sha256"]
    assert prepared.files[0][1].suffix == ".png"


@pytest.mark.parametrize("sha1", [None, "matching", "mismatch"])
def test_原本はPillow上限で失敗せずSHA1不一致候補だけを除外する(
    policy, tmp_path, monkeypatch, sha1,  # noqa: F811
):
    from PIL import Image

    from colorstats.collect.stage import prepare

    image = io.BytesIO()
    Image.new("RGB", (20, 20), "blue").save(image, format="PNG")
    content = image.getvalue()
    expected = hashlib.sha1(content).hexdigest()
    recorded = recorded_thumbnail()
    recorded[1]["query"]["pages"][0]["imageinfo"][0]["sha1"] = {
        None: None, "matching": expected, "mismatch": "0" * 40,
    }[sha1]
    adapter, _ = adapter_for(policy, [Response(r) for r in recorded])
    result = adapter.search(SearchRequest("wikimedia_commons", "castle"))
    first = result.candidates[0]
    following = replace(
        first, source_url=first.source_url + "/next", original_url=first.original_url + "?next",
        rendition={
            **first.rendition, "original": {**first.rendition["original"], "sha1": expected},
        },
    )
    monkeypatch.setattr(adapter, "search", lambda request: replace(
        result, candidates=[first, following],
    ))
    monkeypatch.setattr(adapter, "download", lambda candidate, path: path.write_bytes(content))
    monkeypatch.setattr("colorstats.collect.stage.CommonsAdapter", lambda policy: adapter)
    monkeypatch.setattr("colorstats.collect.stage.existing_rendition", lambda *args: None)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(Image.DecompressionBombError):
        Image.open(io.BytesIO(content))
    discarded, events = [], []
    payload, digest = payload_for(tmp_path)
    prepared = prepare(
        claim_for(payload, digest), discard=lambda request, candidate: discarded.append(candidate),
        observer=lambda event, value: events.append((event, value)),
    )
    assert len(prepared.data["records"]) == (1 if sha1 == "mismatch" else 2)
    assert all(record["received"] == {
        "width": first.width, "height": first.height, "mime": first.mime,
    } for record in prepared.data["records"])
    assert sum(value for event, value in events if event == "downloads") == 2
    if sha1 == "mismatch":
        assert discarded == [first]
        assert prepared.info.parameters["skipped"][0]["reason"] == "original_sha1_mismatch"
        assert prepared.data["records"][0]["candidate"]["source_url"] == following.source_url
        assert set(tmp_path.rglob("*.tmp")) == {path for path, _ in prepared.files}
    else:
        assert not discarded and not prepared.info.parameters["skipped"]


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="隔離PostgreSQL")
@pytest.mark.parametrize("first", ["original", "thumbnail"])
@pytest.mark.parametrize("identity", ["url", "native", "tracking", "same_variant"])
def test_異なるSHAのvariantは独立asset支持に増えず既存値を保つ(
    queue, tmp_path, policy, first, identity,  # noqa: F811
):
    payload, config_hash = payload_for(tmp_path)
    job = queue.enqueue("collect", None, config_hash, payload)
    claim = queue.claim(["collect"])
    adapter, _ = adapter_for(policy, [Response(r) for r in recorded_thumbnail()])
    candidate = asdict(adapter.search(SearchRequest(
        "wikimedia_commons", "castle", download_mode="thumbnail",
    )).candidates[0])
    candidate["rendition"]["variant"] = first
    candidate["original_url"] += "?utm_source=commons.wikimedia.org"
    target = tmp_path / "image.jpg"
    temporary = tmp_path / "image.tmp"
    temporary.write_bytes(b"first")
    record = {
        "candidate": candidate, "sha256": "a" * 64, "logical_path": "raw/first.jpg",
        "target": str(target), "license_class": "open", "retrieved_at": claim.started_at,
        "received": {"width": 1280, "height": 2400, "mime": "image/jpeg"},
    }
    from colorstats.queue import RunInfo

    run_id = queue.complete(claim, RunInfo("open", "test", "0.1.0", "test", {"effective": {}}),
                            lambda session, run: register(
                                session, run, {"payload": payload, "records": [record]},
                            ), [(temporary, target)])
    assert job
    with Session(queue.engine) as session, session.begin():
        run = session.get(ProcessingRun, run_id)
        asset = session.scalars(select(Asset)).one()
        original_quality = copy.deepcopy(asset.quality)
        candidate = copy.deepcopy(candidate)
        candidate["rendition"]["variant"] = "thumbnail" if first == "original" else "original"
        if identity == "same_variant":
            candidate["rendition"]["variant"] = first
        elif identity == "native":
            candidate.update(source_url="https://example.test/new-source",
                             original_url="https://example.test/new-original.jpg")
        elif identity == "tracking":
            candidate["source_url"] = "https://example.test/openverse-landing"
            candidate["original_url"] = candidate["original_url"].partition("?")[0]
            candidate["rendition"].pop("native_id")
        register(session, run, {"payload": payload, "records": [
            {**record, "candidate": candidate, "sha256": "b" * 64},
        ]})
        assert session.scalar(select(func.count()).select_from(Asset)) == 1
        assert session.get(Asset, asset.id).sha256 == "a" * 64
        assert session.get(Asset, asset.id).quality == original_quality
        assert run.parameters["rendition_reused"]
        from colorstats.collect.measurement import record as record_measurement

        for received_sha, duplicates in [("b" * 64, 0), ("a" * 64, 1)]:
            trial = ProcessingRun(
                stage="collect", license_class="open", config_hash="c" * 64,
                code_version="test", taxonomy_version="0.1.0", node="test",
                parameters={"counts": {"duplicate_sha": 0}},
            )
            session.add(trial)
            session.flush()
            record_measurement(session, run, {
                "measurement_run_id": str(trial.id), "records": [{"sha256": received_sha}],
            }, {"a" * 64})
            assert trial.parameters["counts"]["duplicate_sha"] == duplicates
            assert trial.parameters["counts"]["new_sha"] == 1 - duplicates
