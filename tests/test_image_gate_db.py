import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from unittest.mock import Mock

import pytest
from PIL import Image
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from colorstats import api_budget
from colorstats import image_gate as gate
from colorstats.api_budget import BUDGET_KEY, NUSD, PRICING, Ledger, RetryLater
from colorstats.queue import LeaseLost, Queue
from colorstats.queue.core import NonRetryableError
from colorstats.queue.worker import Worker
from colorstats.schema.models import (
    ApiBudget,
    ApiCall,
    Asset,
    Job,
    ProcessingRun,
    ProcessingRunInput,
    Retention,
    RetentionFile,
    Source,
)
from tests.queue_handler import image_gate_prepare, image_gate_request
from tests.test_image_gate import response, verdict
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="CIのPostgreSQL専用",
)


@pytest.fixture
def trial(queue, asset, tmp_path, monkeypatch):
    monkeypatch.setattr(gate.socket, "gethostname", lambda: "ubuntu-1")
    credentials = tmp_path / "credentials"
    credentials.mkdir()
    (credentials / "openai-api-key").write_text("fixture", encoding="utf-8")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credentials))
    image = tmp_path / "original.png"
    Image.new("RGB", (64, 32), "red").save(image)
    with Session(queue.engine) as session, session.begin():
        session.execute(text("TRUNCATE api_budget CASCADE"))
        row = session.get(Asset, asset)
        row.storage_path = str(image)
        row.sha256 = hashlib.sha256(image.read_bytes()).hexdigest()
        row.quality = {"old": "unchanged"}
        row.domain = "real_terrain"
        source = session.get(Source, row.source_id)
        source.policy = {"external_image_review": "openai-store-false",
                         "external_image_review_allowed": True}
        session.add(ApiBudget(key=BUDGET_KEY, cap_nusd=50 * NUSD, pricing=PRICING))
        session.add(Retention(asset_id=asset, expires_at=datetime.now(UTC) + timedelta(days=30),
                              backup_until=datetime.now(UTC) + timedelta(days=60)))
    requests = []

    def request(endpoint, body, key):
        requests.append((endpoint, body))
        result = {"object": "response.input_tokens", "input_tokens": 4000}
        if endpoint == "responses":
            result = response()
        return {"status": 200, "request_id": "req_fixture", "retry_after": None,
                "body": json.dumps(result)}

    monkeypatch.setattr(api_budget, "request", request)
    job_id = gate.enqueue(queue, asset, tmp_path / "gate", budget_key=BUDGET_KEY,
                          code_version="test", execution_authorized=True)
    claim = queue.claim(("review",), job_ids=[job_id])
    return queue, claim, requests


def complete(queue, claim, prepared):
    return queue.complete(claim, prepared.info,
                          lambda session, run: gate.register(session, run, prepared.data),
                          prepared.files)


def test_共有送信待ちを繰り返してもAPI未送信のjobを失敗させない(
    trial, monkeypatch, tmp_path,
):
    queue, claim, requests = trial
    blocker_id = queue.enqueue("review", None, "c" * 64, {})
    with Session(queue.engine) as session, session.begin():
        session.add(ApiCall(budget_key=BUDGET_KEY, job_id=blocker_id,
                            endpoint="responses", attempt=1, input_hash="c" * 64,
                            state="sent", reserved_nusd=1000, response_path="in-flight",
                            details={}))
    monkeypatch.setattr("colorstats.queue.worker._prepare", image_gate_prepare)
    worker = Worker(queue, {"review": "colorstats.collect.quality"}, tmp_path / "stop")
    states, attempts = [], []
    try:
        for _ in range(4):
            if claim is None:
                break
            worker._run_claim(claim)
            with Session(queue.engine) as session, session.begin():
                job = session.get(Job, claim.id)
                states.append(job.status)
                attempts.append(job.attempts)
                job.available_at = datetime.now(UTC) - timedelta(seconds=1)
            claim = queue.claim(("review",), job_ids=[claim.id])
        assert states == ["pending"] * 4
        assert attempts == [0] * 4
        assert requests == []
        with Session(queue.engine) as session, session.begin():
            session.delete(session.scalar(select(ApiCall).where(ApiCall.job_id == blocker_id)))
        worker._run_claim(claim)
    finally:
        worker._stop_prepare()
    with Session(queue.engine) as session:
        job = session.get(Job, claim.id)
        assert job.status == "succeeded" and job.attempts == 1
        assert session.scalar(select(func.count()).select_from(ApiCall)) == 2


def test_子プロセスの実API一時失敗は試行を消費してRetryAfterを維持する(
    trial, monkeypatch, tmp_path,
):
    queue, claim, _ = trial
    monkeypatch.setenv("COLORSTATS_TEST_429", "1")
    monkeypatch.setattr("colorstats.queue.worker._prepare", image_gate_prepare)
    worker = Worker(queue, {"review": "colorstats.collect.quality"}, tmp_path / "stop")
    try:
        worker._run_claim(claim)
    finally:
        worker._stop_prepare()
    with Session(queue.engine) as session:
        job = session.get(Job, claim.id)
        now = session.scalar(select(func.clock_timestamp()))
        assert job.status == "pending" and job.attempts == 1
        assert 295 < (job.available_at - now).total_seconds() <= 300
        assert session.scalar(select(ApiCall.state)) == "retry"
    assert queue.claim(("review",), job_ids=[claim.id]) is None


def test_画像ゲートはleaseより長い処理でも更新して精算済みrunを確定する(
    trial, monkeypatch, tmp_path,
):
    queue, claim, _ = trial
    short = Queue(queue.engine, lease=timedelta(seconds=1))
    short.renew(claim)
    short.renew = Mock(wraps=short.renew)
    monkeypatch.setattr(api_budget, "request", image_gate_request)
    monkeypatch.setattr("colorstats.queue.worker._prepare", image_gate_prepare)
    worker = Worker(short, {"review": "colorstats.collect.quality"}, tmp_path / "stop",
                    poll_interval=0.02)
    worker._available = lambda stage: True
    try:
        worker._run_claim(claim)
    finally:
        worker._stop_prepare()
    with Session(queue.engine) as session:
        call = session.scalar(select(ApiCall).where(ApiCall.endpoint == "responses"))
        assert call.state == "settled" and call.cost_nusd is not None
        job = session.get(Job, claim.id)
        assert job.status == "succeeded" and job.run_id is not None
        assert session.get(ProcessingRun, job.run_id).parameters["kind"] == "image_gate"
    assert short.renew.call_count >= 1


def test_権利確認後のrunと保持登録は旧assetを変更しない(trial):
    queue, claim, requests = trial
    prepared = gate.prepare(queue, claim, key="fixture")
    run_id = complete(queue, claim, prepared)
    assert [item[0] for item in requests] == ["responses/input_tokens", "responses"]
    body = requests[1][1]
    assert body["store"] is False and body["tools"] == []
    assert body["model"] == gate.MODEL and body["reasoning"] == {"effort": "low"}
    assert str(claim.asset_id) not in json.dumps(body)
    with Session(queue.engine) as session:
        row = session.get(Asset, claim.asset_id)
        assert row.quality == {"old": "unchanged"}
        assert row.domain == "real_terrain"
        assert row.subject_id is None
        run = session.get(ProcessingRun, run_id)
        assert run.parameters["identity"] == claim.payload["identity"]
        assert run.parameters["returned_model"] == gate.MODEL
        assert len(run.parameters["calls"]) == 2
        selection = gate.selection(session, claim.asset_id, run_id)
        assert selection["analysis_domain"] == "real_building"
        assert selection["privacy_review_run_id"] is None
        assert selection["image_gate_hash"] == api_budget.digest(run.parameters)
        gate.check_selection(session, selection)
        with pytest.raises(PermissionError):
            gate.check_selection(session, {**selection, "image_gate_hash": "changed"})
        paths = {r.path for r in session.scalars(select(RetentionFile))}
        assert run.parameters["result_path"] in paths
        assert run.parameters["image_path"] in paths
        for call in session.scalars(select(ApiCall)):
            assert call.response_path in paths
            assert call.input_hash == claim.payload["identity_hash"]


@pytest.mark.parametrize("key", ["MODEL", "PROMPT", "POLICY", "SCHEMA", "EFFORT", "PREPROCESS"])
def test_投入後の契約変更は再利用も送信も拒否する(trial, monkeypatch, key):
    queue, claim, requests = trial
    original = getattr(gate, key)
    monkeypatch.setattr(gate, key, original + "changed" if isinstance(original, str)
                        else {**original, "changed": True})
    with pytest.raises(NonRetryableError):
        gate.prepare(queue, claim, key="fixture")
    assert requests == []


def test_同じ機械判定だけ再利用し人の訂正は別runへ追加する(trial, tmp_path):
    queue, claim, requests = trial
    run_id = complete(queue, claim, gate.prepare(queue, claim, key="fixture"))
    repeat_id = gate.enqueue(queue, claim.asset_id, tmp_path / "repeat", budget_key=BUDGET_KEY,
                             code_version="test", execution_authorized=True)
    repeated = queue.claim(("review",), job_ids=[repeat_id])
    repeated_run = complete(queue, repeated, gate.prepare(queue, repeated, key="fixture"))
    assert len(requests) == 2
    human_id = gate.enqueue(queue, claim.asset_id, tmp_path / "human", budget_key=BUDGET_KEY,
                            code_version="test", input_run_id=run_id, reviewer="人の確認者",
                            presented_sha256=claim.payload["identity"]["input_sha256"],
                            correction=verdict(real_people="present"))
    human = queue.claim(("review",), job_ids=[human_id])
    human_run = complete(queue, human, gate.prepare(queue, human))
    with Session(queue.engine) as session:
        assert session.get(ProcessingRun, run_id).parameters["verdict"]["decision"] == "accepted"
        assert session.get(ProcessingRun, repeated_run).parameters["method"] == "api"
        assert session.get(ProcessingRunInput, (human_run, run_id))
        assert session.get(ProcessingRun, human_run).model_name is None
        with pytest.raises(PermissionError):
            gate.selection(session, claim.asset_id, human_run)
    with pytest.raises(ValueError):
        gate.enqueue(queue, claim.asset_id, tmp_path / "wrong", budget_key=BUDGET_KEY,
                     code_version="test", input_run_id=run_id, reviewer="確認者",
                     presented_sha256="unpresented", correction=verdict())
    assert len(requests) == 2


def test_応答保存後の完了DB失敗でも再送しない(trial):
    queue, claim, requests = trial
    prepared = gate.prepare(queue, claim, key="fixture")

    def fail(session, run):
        raise RuntimeError("DB登録失敗")

    with pytest.raises(RuntimeError):
        queue.complete(claim, prepared.info, fail, prepared.files)
    run_id = complete(queue, claim, gate.prepare(queue, claim, key="fixture"))
    assert run_id
    assert len(requests) == 2


def test_応答保存直後の精算DB失敗からファイルで再開する(trial, monkeypatch):
    queue, claim, requests = trial
    save = api_budget.save_private

    def fail_after_save(path, value):
        save(path, value)
        raise KeyboardInterrupt("精算前に停止")

    monkeypatch.setattr(api_budget, "save_private", fail_after_save)
    with pytest.raises(KeyboardInterrupt):
        gate.prepare(queue, claim, key="fixture")
    monkeypatch.setattr(api_budget, "save_private", save)
    complete(queue, claim, gate.prepare(queue, claim, key="fixture"))
    assert len(requests) == 2


def test_lease切れ後も台帳の保存応答を使い二重送信しない(trial):
    queue, claim, requests = trial
    gate.prepare(queue, claim, key="fixture")
    with queue.engine.begin() as connection:
        connection.execute(update(Job).where(Job.id == claim.id).values(
            lease_until=datetime.now(UTC) - timedelta(seconds=1)))
    next_claim = queue.claim(("review",), job_ids=[claim.id])
    with pytest.raises(LeaseLost):
        gate.prepare(queue, claim, key="fixture")
    complete(queue, next_claim, gate.prepare(queue, next_claim, key="fixture"))
    assert len(requests) == 2


def test_タイムアウトは予約を残してバッチ停止し自動再送しない(trial, monkeypatch):
    queue, claim, requests = trial
    original = api_budget.request

    def timeout(endpoint, body, key):
        if endpoint == "responses":
            requests.append((endpoint, body))
            raise TimeoutError("認証本文は出さない")
        return original(endpoint, body, key)

    monkeypatch.setattr(api_budget, "request", timeout)
    with pytest.raises(NonRetryableError):
        gate.prepare(queue, claim, key="fixture")
    with pytest.raises(NonRetryableError):
        gate.prepare(queue, claim, key="fixture")
    assert len(requests) == 2
    with Session(queue.engine) as session:
        call = session.scalar(select(ApiCall).where(ApiCall.endpoint == "responses"))
        assert call.state == "unknown" and call.cost_nusd is None and call.reserved_nusd > 0
        assert session.get(ApiBudget, BUDGET_KEY).stopped


@pytest.mark.parametrize("status,code", [
    (401, "invalid_api_key"), (429, "insufficient_quota"), (400, "unsupported_model"),
])
def test_認証とquotaと非対応countは本判定へ進まない(trial, monkeypatch, status, code):
    queue, claim, requests = trial

    def error(endpoint, body, key):
        requests.append(endpoint)
        return {"status": status, "request_id": "req_error", "retry_after": None,
                "body": json.dumps({"error": {"code": code}})}

    monkeypatch.setattr(api_budget, "request", error)
    with pytest.raises(NonRetryableError):
        gate.prepare(queue, claim, key="fixture")
    assert requests == ["responses/input_tokens"]


@pytest.mark.parametrize("status", [429, 503])
def test_一時HTTP障害はRetryAfterを尊重し連続障害で停止する(trial, monkeypatch, status):
    queue, claim, requests = trial

    def error(endpoint, body, key):
        requests.append(endpoint)
        return {"status": status, "request_id": "req_error", "retry_after": "300",
                "body": json.dumps({"error": {"code": "rate_limit_exceeded"}})}

    monkeypatch.setattr(api_budget, "request", error)
    with pytest.raises(RetryLater) as caught:
        gate.prepare(queue, claim, key="fixture")
    assert caught.value.delay.total_seconds() == 300
    with pytest.raises(RetryLater):
        gate.prepare(queue, claim, key="fixture")
    assert len(requests) == 1
    with Session(queue.engine) as session, session.begin():
        row = session.scalar(select(ApiCall))
        row.details = {**row.details, "retry_at": datetime.now(UTC).isoformat()}
    with pytest.raises(NonRetryableError):
        gate.prepare(queue, claim, key="fixture")
    with Session(queue.engine) as session:
        assert session.get(ApiBudget, BUDGET_KEY).stopped
    assert len(requests) == 2


def test_同時予約で共有capと直列送信を守る(trial, monkeypatch, tmp_path):
    queue, claim, requests = trial
    with Session(queue.engine) as session, session.begin():
        session.get(ApiBudget, BUDGET_KEY).cap_nusd = 2_000_000
    other_id = gate.enqueue(queue, claim.asset_id, tmp_path / "parallel", budget_key=BUDGET_KEY,
                            code_version="test", execution_authorized=True)
    other = queue.claim(("review",), job_ids=[other_id])
    started, resume = Event(), Event()

    def blocking(endpoint, body, key):
        requests.append(endpoint)
        started.set()
        assert resume.wait(10)
        return {"status": 200, "request_id": "req", "retry_after": None,
                "body": json.dumps(response())}

    monkeypatch.setattr(api_budget, "request", blocking)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(Ledger(queue, claim, lambda s: None).call,
                             "responses", {"model": gate.MODEL}, 2_000_000, key="fixture")
        assert started.wait(10)
        try:
            with pytest.raises(RetryLater):
                Ledger(queue, other, lambda s: None).call(
                    "responses", {"model": gate.MODEL}, 2_000_000, key="fixture")
        finally:
            resume.set()
        future.result()
    with pytest.raises(NonRetryableError, match="上限"):
        Ledger(queue, other, lambda s: None).call(
            "responses", {"model": gate.MODEL}, 2_000_000, key="fixture")
    assert requests == ["responses"]
    with Session(queue.engine) as session:
        assert session.scalar(select(func.count()).select_from(ApiCall)) == 1


def test_境界額を超える予約は送らず不明請求も差し引く(trial):
    queue, claim, requests = trial
    with Session(queue.engine) as session, session.begin():
        session.get(ApiBudget, BUDGET_KEY).cap_nusd = 1000
    ledger = Ledger(queue, claim, lambda s: None)
    with pytest.raises(NonRetryableError, match="上限"):
        ledger.call("responses", {}, 1001, key="fixture")
    assert not requests
    with Session(queue.engine) as session, session.begin():
        session.add(ApiCall(budget_key=BUDGET_KEY, job_id=claim.id, endpoint="old",
                            attempt=1, input_hash="a" * 64, state="unknown",
                            reserved_nusd=1000, response_path="missing", details={}))
    with pytest.raises(NonRetryableError, match="上限"):
        ledger.call("responses", {}, 1, key="fixture")
    result, _ = ledger.call("responses/input_tokens", {}, 0, key="fixture")
    assert result["input_tokens"] == 4000


def test_送信前の停止と開始未許可でAPIへ渡さない(trial):
    queue, claim, requests = trial
    with Session(queue.engine) as session, session.begin():
        row = session.get(Asset, claim.asset_id)
        session.get(Source, row.source_id).policy = {"use_stopped": True}
    with pytest.raises(PermissionError):
        gate.prepare(queue, claim, key="fixture")
    assert requests == []


def test_旧assetの保持登録は既存期限と短いbackup条件を延長しない(trial, tmp_path):
    queue, claim, requests = trial
    expiry = datetime.now(UTC) + timedelta(days=2)
    with Session(queue.engine) as session, session.begin():
        record = session.scalar(select(Retention).where(Retention.asset_id == claim.asset_id))
        session.delete(record)
        row = session.get(Asset, claim.asset_id)
        row.quality = {**row.quality, "retention_until": expiry.isoformat()}
        source = session.get(Source, row.source_id)
        source.policy = {**source.policy, "retention": {"raw_days": 30, "backup_days": 7}}
    gate.enqueue(queue, claim.asset_id, tmp_path / "retention", budget_key=BUDGET_KEY,
                 code_version="test")
    with Session(queue.engine) as session:
        record = session.scalar(select(Retention).where(Retention.asset_id == claim.asset_id))
        assert record.expires_at == expiry
        assert record.backup_until == expiry + timedelta(days=7)
        assert session.get(Asset, claim.asset_id).quality["retention_until"] == expiry.isoformat()
    assert not requests


def test_開始未許可は有効な鍵があっても送らない(trial):
    queue, claim, requests = trial
    claim.payload["execution_authorized"] = False
    with pytest.raises(NonRetryableError, match="開始許可"):
        gate.prepare(queue, claim, key="fixture")
    assert not requests


def test_応答を失ったsent台帳は再送せず予約を保全する(trial):
    queue, claim, requests = trial
    with Session(queue.engine) as session, session.begin():
        session.add(ApiCall(
            budget_key=BUDGET_KEY, job_id=claim.id, endpoint="responses", attempt=1,
            input_hash=claim.payload["identity_hash"], state="sent", reserved_nusd=2_000_000,
            response_path=str(claim.payload["artifact_dir"] + "/lost.json"),
            details={"identity": {"request_hash": api_budget.digest({"model": gate.MODEL}),
                                  "pricing": PRICING, "input": claim.payload["identity"]}},
        ))
    with pytest.raises(NonRetryableError, match="再送"):
        Ledger(queue, claim, lambda s: None).call(
            "responses", {"model": gate.MODEL}, 2_000_000, key="fixture")
    assert not requests
    with Session(queue.engine) as session:
        assert session.scalar(select(ApiCall.state)) == "unknown"
        assert session.get(ApiBudget, BUDGET_KEY).stopped


def test_上限予約ちょうどは許可し超過usageは採用しない(trial):
    queue, claim, requests = trial
    cost = api_budget.usage_cost(response()["usage"])
    with Session(queue.engine) as session, session.begin():
        session.get(ApiBudget, BUDGET_KEY).cap_nusd = cost
    result, record = Ledger(queue, claim, lambda s: None).call(
        "responses", {"model": gate.MODEL}, cost, key="fixture")
    assert record["cost_nusd"] == cost
    assert result["model"] == gate.MODEL


def test_予約より多いusageは停止し採用しない(trial):
    queue, claim, requests = trial
    with pytest.raises(NonRetryableError):
        Ledger(queue, claim, lambda s: None).call(
            "responses", {"model": gate.MODEL}, 1, key="fixture")
    with Session(queue.engine) as session:
        assert session.get(ApiBudget, BUDGET_KEY).stopped


@pytest.mark.parametrize("changes", [
    {"status": "incomplete"},
    {"output": [{"type": "message", "content": [{"type": "refusal"}]}]},
    {"output": [{"type": "message", "content": [{"type": "output_text", "text": "{}"}]}]},
    {"output": None},
])
def test_拒否とschema不正を私有artifactへ残して保留する(trial, monkeypatch, changes):
    queue, claim, requests = trial
    original = api_budget.request

    def invalid(endpoint, body, key):
        result = original(endpoint, body, key)
        if endpoint == "responses":
            result["body"] = json.dumps(response(**changes))
        return result

    monkeypatch.setattr(api_budget, "request", invalid)
    prepared = gate.prepare(queue, claim, key="fixture")
    run_id = complete(queue, claim, prepared)
    with Session(queue.engine) as session:
        assert session.get(ProcessingRun, run_id).parameters["verdict"]["decision"] == "pending"
        with pytest.raises(PermissionError):
            gate.selection(session, claim.asset_id, run_id)


def test_usage欠測は0円にせず停止する(trial, monkeypatch):
    queue, claim, requests = trial
    original = api_budget.request

    def missing(endpoint, body, key):
        result = original(endpoint, body, key)
        if endpoint == "responses":
            result["body"] = json.dumps(response(usage=None))
        return result

    monkeypatch.setattr(api_budget, "request", missing)
    with pytest.raises(NonRetryableError):
        gate.prepare(queue, claim, key="fixture")
    with Session(queue.engine) as session:
        row = session.scalar(select(ApiCall).where(ApiCall.endpoint == "responses"))
        assert row.cost_nusd is None and row.reserved_nusd > 0


@pytest.mark.parametrize("changes", [
    {"model": "gpt-6.1-sol"}, {"service_tier": "priority"},
    {"usage": {"input_tokens": 4000, "output_tokens": 100,
               "input_tokens_details": {"cached_tokens": 0}}},
])
def test_別modelとtierとcache欠測は料金不明として停止する(trial, monkeypatch, changes):
    queue, claim, requests = trial
    original = api_budget.request

    def wrong_model(endpoint, body, key):
        result = original(endpoint, body, key)
        if endpoint == "responses":
            result["body"] = json.dumps(response(**changes))
        return result

    monkeypatch.setattr(api_budget, "request", wrong_model)
    with pytest.raises(NonRetryableError):
        gate.prepare(queue, claim, key="fixture")
    with Session(queue.engine) as session:
        row = session.scalar(select(ApiCall).where(ApiCall.endpoint == "responses"))
        assert row.cost_nusd is None and row.state == "unknown"
        assert session.get(ApiBudget, BUDGET_KEY).stopped


def test_count成功は判定要求の連続障害を解除しない(trial, monkeypatch, tmp_path):
    queue, claim, requests = trial
    original = api_budget.request

    def unavailable(endpoint, body, key):
        result = original(endpoint, body, key)
        if endpoint == "responses":
            result.update(status=503, retry_after="1", body="{}")
        return result

    monkeypatch.setattr(api_budget, "request", unavailable)
    with pytest.raises(RetryLater):
        gate.prepare(queue, claim, key="fixture")
    other_id = gate.enqueue(queue, claim.asset_id, tmp_path / "other", budget_key=BUDGET_KEY,
                            code_version="test", execution_authorized=True)
    other = queue.claim(("review",), job_ids=[other_id])
    with pytest.raises(NonRetryableError):
        gate.prepare(queue, other, key="fixture")
    with Session(queue.engine) as session:
        assert session.get(ApiBudget, BUDGET_KEY).stopped
        assert session.get(ApiBudget, BUDGET_KEY).failures == 2


def test_取得品質reviewの既存監査は専用経路に入らない(trial, monkeypatch, tmp_path):
    queue, claim, requests = trial
    other_id = queue.enqueue("review", None, "b" * 64, {"kind": "quality_audit"})
    other = queue.claim(("review",), job_ids=[other_id])
    called = []
    monkeypatch.setattr(gate, "run", lambda *args, **kw: called.append(True))
    worker = Worker(queue, {"review": "tests.queue_handler"}, tmp_path / "stop")
    # 計算プロセスの起動地点まで進むことを確認する。
    monkeypatch.setattr(worker, "_start_prepare", lambda: (_ for _ in ()).throw(
        NonRetryableError("既存経路")))
    worker._run_claim(other)
    assert called == []
    with Session(queue.engine) as session:
        assert session.get(Job, other.id).failure_reason.endswith("既存経路")


def test_workerはimage_gateだけ専用経路へdispatchする(trial, monkeypatch, tmp_path):
    queue, claim, requests = trial
    monkeypatch.setattr("colorstats.queue.worker._prepare", image_gate_prepare)
    worker = Worker(queue, {"review": "colorstats.collect.quality"}, tmp_path / "stop")
    try:
        worker._run_claim(claim)
    finally:
        worker._stop_prepare()
    with Session(queue.engine) as session:
        job = session.get(Job, claim.id)
        assert job.status == "succeeded"
        assert session.get(ProcessingRun, job.run_id).parameters["kind"] == "image_gate"
    assert requests == []
