import copy
import io
import json
import socket
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPHandler
from urllib.response import addinfourl

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from colorstats.collect import bias
from colorstats.collect.http import MeasurementLimit
from colorstats.collect.measurement import Meter, report
from colorstats.collect.openverse import OpenverseAdapter
from colorstats.collect.policy import load_policy
from colorstats.schema.models import Asset, CollectionReservation, ProcessingRun, Subject
from tests.test_collect import RECORDED, Clock, Response, adapter_for, payload_for
from tests.test_collect_http import make_client
from tests.test_collection_bias import (
    DB,
    ROOT,
    Adapter,
    candidate,
    claims,
    prepared_job,
    request,
    subjects,
)
from tests.test_collection_bias import config as config
from tests.test_openverse import FIXTURE, source_page
from tests.test_queue import database, expire  # noqa: F401
from tests.test_queue import queue as queue


@pytest.fixture
def measured(config):
    config["measurement"] = {
        "id": "fixture-77",
        "api_requests_per_stratum": 20,
        "http_requests_per_stratum": 40,
    }
    return config


@pytest.mark.parametrize(
    "failure", [TimeoutError(), HTTPError("https://example.test", 503, "busy", {}, None)]
)
def test_HTTP再試行とtimeoutも要求の分母へ含む(failure):
    from colorstats.collect.commons import CommonsAdapter

    adapter, calls = make_client(
        ("wikimedia_commons", CommonsAdapter), [failure, Response(b"{}")], example_kind="api"
    )
    counts = Counter()
    adapter.observer = lambda event, value: counts.update({event: value})
    if isinstance(failure, TimeoutError):
        with pytest.raises(TimeoutError):
            adapter.get("https://example.test", api=True)
        assert counts == {"api_request": 1, "timeouts": 1, "network_api_seconds": 0.0}
    else:
        adapter.get("https://example.test", api=True)
        assert counts == {
            "api_request": 2,
            "responses": 2,
            "bytes": 2,
            "network_api_seconds": 0.0,
            "backoff_seconds": 5.0,
        }
    assert counts["api_request"] == len(calls)


def test_body_read_timeoutもAPI応答時間に含め5秒cooldownを守る():
    from colorstats.collect.commons import CommonsAdapter

    clock = Clock()

    class SlowTimeout(Response):
        def read(self, *args):
            clock.now += 2
            raise TimeoutError

    adapter, calls = make_client(
        ("wikimedia_commons", CommonsAdapter),
        [SlowTimeout(b""), Response(b"{}")],
        clock=clock,
        example_kind="api",
    )
    observed = []
    adapter.observer = lambda event, value: observed.append((event, value))
    with pytest.raises(TimeoutError):
        adapter.get("https://example.test")
    adapter.get("https://example.test")
    assert calls == [("https://example.test", 0), ("https://example.test", 7)]
    assert ("network_api_seconds", 2) in observed


@DB
def test_並行要求と再試行でAPI枠を超えない(queue, measured, tmp_path):
    measured["measurement"]["api_requests_per_stratum"] = 1
    payload, _ = payload_for(tmp_path)
    payload["bias"] = measured
    payload["request"]["stratum"] = request().stratum
    for index in range(2):
        queue.enqueue("collect", None, f"{index:064x}", payload)
    workers = [queue.claim(["collect"]) for _ in range(2)]
    meters = [Meter(queue, claim) for claim in workers]
    barrier = threading.Barrier(2)

    def send(meter):
        barrier.wait(5)
        try:
            meter.observe("api_request")
            return "sent"
        except MeasurementLimit:
            return "stopped"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(send, meters)) == ["sent", "stopped"]
    queue.fail(workers[0], "fixture")
    retry = queue.claim(["collect"])
    with pytest.raises(MeasurementLimit):
        Meter(queue, retry).observe("api_request")
    with Session(queue.engine) as session:
        assert (
            report(session, "fixture-77")["strata"][request().stratum]["counts"]["api_requests"]
            == 1
        )


@DB
def test_URL予約の競合と失効回収と再発見を抑止する(queue, measured):
    first, second = claims(queue, measured)
    assert bias.reserve(queue, first, measured, request(), candidate()) is None
    assert bias.reserve(queue, second, measured, request(), candidate()) == "reserved_url"
    expire(queue, first)
    assert bias.reserve(queue, second, measured, request(), candidate()) is None
    with Session(queue.engine) as session:
        assert session.scalar(select(func.count()).select_from(CollectionReservation)) == 1


@DB
def test_SHA重複と権利と取得件数を分け検索履歴を保存する(queue, measured, tmp_path, monkeypatch):
    subjects(queue)
    items = [replace(candidate(i), attribution="fixture") for i in range(3)]
    items[2] = replace(items[2], license="cc-by-sa-4.0")
    adapter = Adapter(items)
    adapter.download = lambda item, path: path.write_bytes(
        b"same" if item.rank < 2 else b"share-alike"
    )
    claim = prepared_job(queue, measured, tmp_path, monkeypatch, adapter)
    prepared = bias.prepare(claim)
    run_id = queue.complete(
        claim, prepared.info, lambda s, r: bias.register(s, r, prepared.data), prepared.files
    )
    with Session(queue.engine) as session:
        layer = report(session, "fixture-77")["strata"][request().stratum]
        counts = layer["counts"]
        assert counts["downloads"] == counts["registered"] == 3
        assert counts["new_sha"] == 2 and counts["eligible_new_sha"] == 1
        assert counts["duplicate_sha"] == 1
        assert counts["confirmed_subjects"] == 0
        assert layer["d15_exclusions"]["license_conditions"] == 1
        assert layer["eligible_new_sha_per_api_request"] is None
        history = layer["history"][0]
        assert history["search"]["next_offset"] == 30
        assert history["search"]["request"] == claim.payload["request"]
        assert session.get(ProcessingRun, run_id).parameters["measurement_run_id"]
    other = claims(queue, measured, 1)[0]
    assert bias.reserve(queue, other, measured, request(), items[0]) == "rediscovered_url"
    assert (
        bias.reserve(
            queue,
            other,
            measured,
            request(),
            replace(items[0], source_url="https://example.test/other"),
        )
        == "rediscovered_url"
    )
    adapter.items = [replace(candidate(5), attribution="fixture")]
    adapter.download = lambda item, path: path.write_bytes(b"same")
    queue.enqueue("collect", None, "f" * 64, claim.payload)
    next_claim = queue.claim(["collect"])
    prepared = bias.prepare(next_claim)
    queue.complete(
        next_claim, prepared.info, lambda s, r: bias.register(s, r, prepared.data), prepared.files
    )
    with Session(queue.engine) as session:
        counts = report(session, "fixture-77")["strata"][request().stratum]["counts"]
        assert counts["duplicate_sha"] == 2 and counts["eligible_new_sha"] == 1


@DB
def test_timeout試行が再成功しても通信分母とbyteを失わない(queue, measured, tmp_path, monkeypatch):
    from colorstats.collect.policy import load_policy

    policy = load_policy(ROOT / "configs/source_policy.yaml", "wikimedia_commons")
    failed, calls = adapter_for(policy, [TimeoutError()])
    claim = prepared_job(queue, measured, tmp_path, monkeypatch, failed)
    with pytest.raises(TimeoutError):
        bias.prepare(claim)
    queue.fail(claim, "fixture timeout")
    retry = queue.claim(["collect"])
    recorded = copy.deepcopy(RECORDED)
    ext = recorded[1]["query"]["pages"][0]["imageinfo"][0]["extmetadata"]
    ext["License"]["value"] = "cc0"
    responses = [Response(r) for r in recorded] + [Response(b"image")]
    byte_count = sum(len(r.getvalue()) for r in responses)
    adapter, success_calls = adapter_for(policy, responses)
    monkeypatch.setattr(bias.stage, "CommonsAdapter", lambda _: adapter)
    prepared = bias.prepare(retry)
    queue.complete(
        retry, prepared.info, lambda s, r: bias.register(s, r, prepared.data), prepared.files
    )
    with Session(queue.engine) as session:
        layer = report(session, "fixture-77")["strata"][request().stratum]
        counts = layer["counts"]
        assert layer["attempts"] == 2 and layer["states"] == {"failed": 1, "committed": 1}
        assert counts["requests"] == len(calls) + len(success_calls) == 4
        assert counts["api_requests"] == 3 and counts["responses"] == 3
        assert counts["timeouts"] == 1 and counts["bytes"] == byte_count
        assert counts["candidates"] == counts["verified"] == counts["eligible_new_sha"] == 1
        assert layer["eligible_new_sha_per_api_request"] == pytest.approx(1 / 3)


@DB
def test_API枠で停止し追加通信せず継続も記録しない(queue, measured, tmp_path, monkeypatch):
    from colorstats.collect.policy import load_policy

    measured["measurement"]["api_requests_per_stratum"] = 1
    policy = load_policy(ROOT / "configs/source_policy.yaml", "wikimedia_commons")
    adapter, calls = adapter_for(policy, [Response(RECORDED[0])])
    claim = prepared_job(queue, measured, tmp_path, monkeypatch, adapter)
    prepared = bias.prepare(claim)
    assert len(calls) == 1 and prepared.info.parameters["stop_reason"] == "api_limit"
    assert prepared.info.parameters["next_offset"] is None
    queue.complete(
        claim, prepared.info, lambda s, r: bias.register(s, r, prepared.data), prepared.files
    )
    with Session(queue.engine) as session:
        assert session.scalar(select(func.count()).select_from(Asset)) == 0


@DB
def test_旧biasジョブが残れば測定計画を投入しない(queue, measured, tmp_path):
    old = copy.deepcopy(measured)
    old.pop("measurement")
    claims(queue, old, 1)
    with pytest.raises(ValueError, match="異なる偏り設定"):
        bias.plan(
            queue,
            measured,
            policy_path=ROOT / "configs/source_policy.yaml",
            storage_config=tmp_path / "unused",
            host="test",
            code_version="test",
        )


@DB
def test_画像枠到達後は検索も原本取得も行わない(queue, measured, tmp_path, monkeypatch):
    measured["strata"][0]["images"] = 1
    first = claims(queue, measured, 1)[0]
    assert bias.reserve(queue, first, measured, request(), candidate()) is None
    adapter = Adapter([])
    adapter.search = lambda _: pytest.fail("満了層への検索は禁止")
    payload, digest = payload_for(tmp_path)
    payload["bias"] = measured
    payload["request"]["stratum"] = request().stratum
    queue.enqueue("collect", None, digest, payload)
    claim = queue.claim(["collect"])
    monkeypatch.setenv("DATABASE_URL", queue.engine.url.render_as_string(hide_password=False))
    monkeypatch.setattr(bias.stage, "CommonsAdapter", lambda _: adapter)
    prepared = bias.prepare(claim)
    assert prepared.info.parameters["stop_reason"] == "image_target_reached"


@DB
def test_確定subjectは後続の根拠付き同定後に異なり数で数える(
    queue, measured, tmp_path, monkeypatch
):
    subjects(queue)
    claim = prepared_job(
        queue,
        measured,
        tmp_path,
        monkeypatch,
        Adapter([replace(candidate(), attribution="fixture")]),
    )
    prepared = bias.prepare(claim)
    queue.complete(
        claim, prepared.info, lambda s, r: bias.register(s, r, prepared.data), prepared.files
    )
    with Session(queue.engine) as session, session.begin():
        asset = session.scalars(select(Asset)).one()
        assert asset.subject_id is None
        assert (
            report(session, "fixture-77")["strata"][request().stratum]["counts"][
                "confirmed_subjects"
            ]
            == 0
        )
        asset.subject_id = session.scalars(select(Subject)).first().id
        asset.quality = {**asset.quality, "subject_inference": {"state": "confirmed"}}
    with Session(queue.engine) as session:
        counts = report(session, "fixture-77")["strata"][request().stratum]["counts"]
        assert counts["confirmed_subjects"] == counts["new_subjects"] == 1


@DB
def test_カテゴリ候補はCommonsだけで初期ページとAPI継続を使う(queue, measured, tmp_path):
    measured["strata"][0]["commons_categories"] = ["Himeji Castle"]
    measured["search"]["providers"] = ["wikimedia_commons", "openverse"]
    storage = tmp_path / "storage.yaml"
    storage.write_text("storage: {}", encoding="utf-8")
    options = dict(
        policy_path=ROOT / "configs/source_policy.yaml",
        storage_config=storage,
        host="test",
        code_version="test",
        seed=77,
    )
    ids = bias.plan(queue, measured, **options)
    from colorstats.schema.models import Job
    from tests.test_queue import INFO

    with Session(queue.engine) as session:
        jobs = [session.get(Job, jid) for jid in ids]
        assert all(job.payload["request"]["page"] == 0 for job in jobs)
        category = [
            job for job in jobs if job.payload["request"]["query"].startswith("incategory:")
        ]
        assert len(category) == 1
        assert category[0].payload["request"]["provider"] == "wikimedia_commons"
    claim = queue.claim(["collect"])
    queue.complete(claim, replace(INFO, parameters={"next_offset": 17}), lambda s, r: None)
    added = set(bias.plan(queue, measured, **options)) - set(ids)
    assert len(added) == 1
    with Session(queue.engine) as session:
        continued = session.get(Job, added.pop()).payload["request"]
        assert continued["page"] == 1 and continued["offset"] == 17


@DB
@pytest.mark.parametrize("licenses", [("cc0", "cc-by-sa-4.0"), ("cc-by-sa-4.0", "cc0")])
def test_同一SHAの適格性を同バッチの検索順に依存させない(
    queue, measured, tmp_path, monkeypatch, licenses
):
    items = [
        replace(candidate(i), attribution="fixture", license=name)
        for i, name in enumerate(licenses)
    ]
    adapter = Adapter(items)
    adapter.download = lambda item, path: path.write_bytes(b"same")
    claim = prepared_job(queue, measured, tmp_path, monkeypatch, adapter)
    prepared = bias.prepare(claim)
    queue.complete(
        claim, prepared.info, lambda s, r: bias.register(s, r, prepared.data), prepared.files
    )
    with Session(queue.engine) as session:
        counts = report(session, "fixture-77")["strata"][request().stratum]["counts"]
        assert counts["new_sha"] == counts["eligible_new_sha"] == counts["duplicate_sha"] == 1


@DB
def test_同じ測定IDでsource_policyを緩和できない(queue, measured, tmp_path):
    payload, _ = payload_for(tmp_path)
    payload["bias"] = measured
    payload["request"]["stratum"] = request().stratum
    queue.enqueue("collect", None, "a" * 64, payload)
    Meter(queue, queue.claim(["collect"]))
    payload["policy"]["min_interval"] /= 2
    queue.enqueue("collect", None, "b" * 64, payload)
    with pytest.raises(ValueError, match="source_policy"):
        Meter(queue, queue.claim(["collect"]))


@pytest.mark.parametrize("cap", [1, 2])
@pytest.mark.parametrize("api", [False, True])
def test_既定openerのリダイレクトも枠待機と応答byteを計数する(monkeypatch, cap, api):
    from colorstats.collect.http import HttpClient

    clock, counts, calls = Clock(), Counter(), []
    policy = load_policy(ROOT / "configs/source_policy.yaml", "openverse")
    policy["hosts"]["example.test"] = {"kind": "page"}

    def forbidden(*args, **kwargs):
        pytest.fail("外部ネットワークへの接続は禁止")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    def http_open(handler, req):
        calls.append((req.full_url, clock.now))
        assert req.get_header("User-agent") == policy["user_agent"]
        redirect = req.full_url.endswith("/first")
        response = addinfourl(
            io.BytesIO(b"redirect" if redirect else b"{}"),
            {"Location": "/final"} if redirect else {},
            req.full_url,
            302 if redirect else 200,
        )
        response.msg = "fixture"
        return response

    monkeypatch.setattr(HTTPHandler, "http_open", http_open)
    client = HttpClient(policy, clock=clock.clock, wait=clock.wait)

    def observe(event, value):
        if event in ("request", "api_request"):
            if counts["requests"] >= cap:
                raise MeasurementLimit("http_limit")
            counts["requests"] += 1
            if api:
                counts["api_requests"] += 1
        else:
            counts[event] += value

    client.observer = observe
    if cap == 1:
        with pytest.raises(MeasurementLimit):
            client.get("http://example.test/first", api=api)
    else:
        assert client.get("http://example.test/first", api=api) == {}
    assert len(calls) == counts["requests"] == counts["responses"] == cap
    assert counts["bytes"] == (8 if cap == 1 else 10)
    if cap == 2:
        assert [time for _, time in calls] == [0, policy["min_interval"]]
    assert counts["api_requests"] == (cap if api else 0)


def openverse_job(queue, measured, tmp_path, monkeypatch, responses):
    policy = load_policy(ROOT / "configs/source_policy.yaml", "openverse")
    clock, calls = Clock(), []
    values = iter(responses)

    def opener(req, **kwargs):
        calls.append(req.full_url)
        response = next(values)
        if isinstance(response, Exception):
            raise response
        return response

    adapter = OpenverseAdapter(policy, opener=opener, clock=clock.clock, wait=clock.wait)
    payload, digest = payload_for(tmp_path)
    payload["bias"] = measured
    payload["request"].update(provider="openverse", stratum=request().stratum, limit=2)
    payload["policy"] = policy
    queue.enqueue("collect", None, digest, payload)
    claim = queue.claim(["collect"])
    monkeypatch.setenv("DATABASE_URL", queue.engine.url.render_as_string(hide_password=False))
    monkeypatch.setattr(bias.stage, "OpenverseAdapter", lambda _: adapter)
    return claim, calls


@DB
@pytest.mark.parametrize("license_name,expected", [("by", 1), ("by-sa", 0)])
def test_Openverseの照合済みBYを正規化しSA除外を維持する(
    queue, measured, tmp_path, monkeypatch, license_name, expected
):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    item = data["results"][0]
    item["license"] = license_name
    item["license_url"] = (
        f"https://creativecommons.org/licenses/{license_name}/{item['license_version']}/"
    )
    data["results"] = [item]
    claim, _ = openverse_job(
        queue,
        measured,
        tmp_path,
        monkeypatch,
        [
            Response(data),
            Response(source_page(item).encode()),
            Response(b"original"),
        ],
    )
    prepared = bias.prepare(claim)
    queue.complete(
        claim, prepared.info, lambda s, r: bias.register(s, r, prepared.data), prepared.files
    )
    with Session(queue.engine) as session:
        layer = report(session, "fixture-77")["strata"][request().stratum]
        assert layer["counts"]["eligible_new_sha"] == expected
        assert layer["d15_exclusions"]["license_conditions"] == 1 - expected
        assert session.scalars(select(Asset)).one().quality["license"] == license_name


@DB
def test_原本取得途中の枠停止でも取得済み原本を確定する(queue, measured, tmp_path, monkeypatch):
    measured["measurement"]["http_requests_per_stratum"] = 4
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    claim, calls = openverse_job(
        queue,
        measured,
        tmp_path,
        monkeypatch,
        [
            Response(data),
            *[Response(source_page(i).encode()) for i in data["results"]],
            Response(b"original"),
        ],
    )
    prepared = bias.prepare(claim)
    assert len(calls) == 4 and len(prepared.data["records"]) == len(prepared.files) == 1
    assert prepared.files[0][0].read_bytes() == b"original"
    assert prepared.info.parameters["stop_reason"] == "http_limit"
    assert prepared.info.parameters["api_next_offset"] == 2
    assert prepared.info.parameters["next_offset"] is None
    queue.complete(
        claim, prepared.info, lambda s, r: bias.register(s, r, prepared.data), prepared.files
    )
    with Session(queue.engine) as session:
        asset = session.scalars(select(Asset)).one()
        assert Path(asset.storage_path).read_bytes() == b"original"
        counts = report(session, "fixture-77")["strata"][request().stratum]["counts"]
        assert counts["registered"] == counts["eligible_new_sha"] == 1
        assert session.scalar(select(func.count()).select_from(CollectionReservation)) == 1


@DB
def test_照合途中の枠停止でも除外URLと受信済み継続位置を保存する(
    queue, measured, tmp_path, monkeypatch
):
    measured["measurement"]["http_requests_per_stratum"] = 2
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    claim, calls = openverse_job(
        queue, measured, tmp_path, monkeypatch, [Response(data), Response(b"unverified")]
    )
    prepared = bias.prepare(claim)
    assert len(calls) == 2
    with Session(queue.engine) as session:
        history = report(session, "fixture-77")["strata"][request().stratum]["history"][0]
        search = history["search"]
        assert "network_api_seconds" in history["counts"]
        assert history["database_timing"]["lock_wait_seconds"] >= 0
        assert history["database_timing"]["processing_seconds"] >= 0
        assert history["database_timing"]["commit_seconds"] >= 0
        assert history["elapsed_seconds"] >= 0
        assert search["effective"]["api"] == "Openverse API v1"
        assert search["api_next_offset"] == 2 and not search["search_complete"]
        assert search["skipped"][0]["source_url"] == data["results"][0]["foreign_landing_url"]
        assert search["skipped"][0]["reason"] == "source_license_or_author_unverified"
        assert search["skipped"][1]["reason"] == "verification_stopped:http_limit"
        assert history["counts"]["excluded:source_license_or_author_unverified"] == 1
    queue.complete(
        claim, prepared.info, lambda s, r: bias.register(s, r, prepared.data), prepared.files
    )


@DB
def test_取得失敗時にも先行除外と検索条件を保存する(queue, measured, tmp_path, monkeypatch):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    claim, _ = openverse_job(
        queue,
        measured,
        tmp_path,
        monkeypatch,
        [
            Response(data),
            Response(b"unverified"),
            Response(source_page(data["results"][1]).encode()),
            TimeoutError(),
        ],
    )
    with pytest.raises(TimeoutError):
        bias.prepare(claim)
    with Session(queue.engine) as session:
        history = report(session, "fixture-77")["strata"][request().stratum]["history"][0]
        assert history["state"] == "failed"
        search = history["search"]
        assert search["api_next_offset"] == 2 and search["failure"] == "TimeoutError"
        assert search["effective"]["q"] == claim.payload["request"]["query"]
        assert search["skipped"][0]["original_url"] == data["results"][0]["url"]
        assert session.scalar(select(func.count()).select_from(CollectionReservation)) == 0


@DB
def test_異なる出典でも同バッチの原本URLを再取得しない(queue, measured, tmp_path, monkeypatch):
    items = [replace(candidate(i), original_url=candidate().original_url) for i in range(2)]
    adapter = Adapter(items)
    claim = prepared_job(queue, measured, tmp_path, monkeypatch, adapter)
    prepared = bias.prepare(claim)
    assert len(adapter.downloaded) == 1
    assert prepared.info.parameters["skipped"][0]["reason"] == "reserved_url"
    queue.complete(
        claim, prepared.info, lambda s, r: bias.register(s, r, prepared.data), prepared.files
    )
    with Session(queue.engine) as session:
        asset = session.scalars(select(Asset)).one()
        assert (
            "_original_url" not in asset.search_parameters["collection_bias"]["intended_attributes"]
        )


@DB
def test_Commonsが供給元枠を使い切ってもOpenverse枠を残す(queue, measured, tmp_path):
    measured["measurement"]["providers"] = {
        "wikimedia_commons": {"api_requests": 1, "http_requests": 2},
        "openverse": {"api_requests": 1, "http_requests": 2},
    }
    payload, _ = payload_for(tmp_path)
    payload["bias"] = measured
    payload["request"]["stratum"] = request().stratum
    queue.enqueue("collect", None, "a" * 64, payload)
    commons = Meter(queue, queue.claim(["collect"]))
    commons.observe("api_request")
    with pytest.raises(MeasurementLimit, match="provider_api_limit"):
        commons.observe("api_request")
    payload["request"]["provider"] = "openverse"
    queue.enqueue("collect", None, "b" * 64, payload)
    openverse = Meter(queue, queue.claim(["collect"]))
    openverse.observe("api_request")
    with Session(queue.engine) as session:
        assert (
            report(session, "fixture-77")["strata"][request().stratum]["counts"]["api_requests"]
            == 2
        )


@DB
def test_Openverse長周期枠は別jobとworker再生成後もDB台帳で復元する(
    queue, measured, tmp_path
):
    from colorstats.collect.policy import load_policy

    measured["measurement"]["id"] = "fixture-openverse-1"
    payload, _ = payload_for(tmp_path)
    payload["bias"] = copy.deepcopy(measured)
    payload["request"].update(provider="openverse", stratum=request().stratum)
    payload["policy"] = load_policy(ROOT / "configs/source_policy.yaml", "openverse")
    host_policy = payload["policy"]["hosts"]["api.openverse.org"]
    queue.enqueue("collect", None, "e" * 64, payload)
    first = queue.claim(["collect"])
    first_meter = Meter(queue, first)
    for _ in range(host_policy["api_windows"][0]["limit"]):
        assert first_meter.reserve_quota(
            "api.openverse.org", "api", host_policy["api_windows"]
        ) == 0
    with Session(queue.engine) as session:
        assert any(
            event["host"] == "api.openverse.org"
            for run in session.scalars(select(ProcessingRun))
            for event in run.parameters.get("quota_events", [])
        )
    queue.fail(first, "restart fixture")

    queue.enqueue("collect", None, "f" * 64, payload)
    restarted_worker_claim = queue.claim(["collect"])
    next_meter = Meter(queue, restarted_worker_claim)
    assert next_meter.reserve_quota(
        "api.openverse.org", "api", host_policy["api_windows"]
    ) >= 3599


@DB
def test_stage_observerとmeasurement台帳へ秘密queryを残さない(
    queue, measured, tmp_path, monkeypatch
):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    item = data["results"][0]
    item["foreign_landing_url"] = "https://openverse.org/page?access_token=private"
    item["url"] = "https://upload.wikimedia.org/image?signature=private"
    claim, _ = openverse_job(
        queue, measured, tmp_path, monkeypatch, [Response(data), Response(b"unverified")]
    )
    prepared = bias.prepare(claim)
    assert "private" not in json.dumps(prepared.info.parameters)
    with Session(queue.engine) as session:
        search = report(session, "fixture-77")["strata"][request().stratum]["history"][0]["search"]
        assert "private" not in json.dumps(search)
