"""送信前予約と応答の先行保存。失効した試行も送信済み台帳を引き継ぐ。"""

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sqlalchemy import func, select

from colorstats import retention
from colorstats.queue.core import NonRetryableError
from colorstats.schema.models import ApiBudget, ApiCall

NUSD = 1_000_000_000
BUDGET_KEY = "issue114-image-gate"
PRICING = {
    "version": "openai-standard-2026-11-07-v2",
    "input_nusd": 100, "cached_nusd": 10, "write_nusd": 125,
    "write_12h_nusd": 250, "output_nusd": 500,
    "count_nusd": 0,
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def save_private(path, value):
    """同一filesystemで応答を先に永続化する。既存の確定応答は置換しない。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".pending")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(temporary, path)
    temporary.unlink()
    if os.name != "nt":
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


class RetryLater(NonRetryableError):
    def __init__(self, seconds, *, reason="画像判定APIの一時障害。再開時刻まで待機します"):
        super().__init__(reason)
        self.delay = timedelta(seconds=seconds)


class WaitForSend(RetryLater):
    """送信前の待機。API失敗の試行数を消費しない。"""

    def __init__(self, seconds):
        super().__init__(seconds, reason="画像判定APIの送信再開待ち")


def retry_delay(value):
    try:
        return max(1, int(value))
    except (ValueError, TypeError):
        try:
            return max(1, int((parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()))
        except (ValueError, TypeError, OverflowError):
            return 30


def request(endpoint, body, key):
    """固定OpenAI endpointへ一度だけ送る。認証・画像・応答をログへ出さない。"""
    req = Request("https://api.openai.com/v1/" + endpoint,
                  data=json.dumps(body).encode(), headers={
                      "Authorization": "Bearer " + key, "Content-Type": "application/json",
                  }, method="POST")
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    try:
        response = build_opener(NoRedirect).open(req, timeout=60)
    except HTTPError as error:
        response = error
    with response:
        return {"status": response.code, "request_id": response.headers.get("x-request-id"),
                "retry_after": response.headers.get("Retry-After"),
                "body": response.read().decode("utf-8")}


def usage_cost(usage, *, cache_ttl="30m"):
    """実usageをStandard料金で精算する。書込み内訳の欠測・不正は確定額にしない。

    TTL別内訳が省略された場合は要求のTTLを使う。API既定値は30m。
    """
    if not isinstance(usage, dict):
        return None
    counts = [usage.get(key) for key in ("input_tokens", "output_tokens")]
    if any(type(value) is not int or value < 0 for value in counts):
        return None
    details = usage.get("input_tokens_details")
    required = {"cached_tokens", "cache_write_tokens"}
    if (not isinstance(details, dict) or not required <= set(details)
            or set(details) - required - {"cache_write_tokens_details"}
            or cache_ttl not in {"30m", "12h"}):
        return None
    cached, writes = (details[key] for key in ("cached_tokens", "cache_write_tokens"))
    if (any(type(v) is not int or v < 0 for v in (cached, writes))
            or cached + writes > counts[0]):
        return None
    breakdown = details.get("cache_write_tokens_details")
    short, long = (writes, 0) if cache_ttl == "30m" else (0, writes)
    if breakdown is not None:
        if (not isinstance(breakdown, dict)
                or set(breakdown) != {"ttl_30m_tokens", "ttl_12h_tokens"}):
            return None
        short, long = (breakdown[k] for k in ("ttl_30m_tokens", "ttl_12h_tokens"))
        if (any(type(v) is not int or v < 0 for v in (short, long))
                or short + long != writes):
            return None
    return ((counts[0] - cached - writes) * PRICING["input_nusd"]
            + cached * PRICING["cached_nusd"] + short * PRICING["write_nusd"]
            + long * PRICING["write_12h_nusd"]
            + counts[1] * PRICING["output_nusd"])


class Ledger:
    """同じ予算の送信を直列化する。通信中はDB取引を保持しない。

    予算は運用者が明示登録し、実行時の自動増額・自動再開は行わない。
    sent/unknownは予約額を維持する。保存応答がないsentを再送しない。
    """

    def __init__(self, queue, claim, check):
        self.queue, self.claim, self.check = queue, claim, check

    def call(self, endpoint, body, reserved, *, key):
        payload = self.claim.payload
        if payload["budget_key"] != BUDGET_KEY:
            raise NonRetryableError("評価・再試行を含め同じ画像判定予算を使用してください")
        identity = {"request_hash": digest(body), "pricing": PRICING,
                    "input": payload["identity"]}
        recovered = False
        with self.queue._transaction() as session:
            budget = session.scalars(select(ApiBudget).where(
                ApiBudget.key == payload["budget_key"],
            ).with_for_update()).one()
            self.queue._owned(session, self.claim)
            self.check(session)
            previous = session.scalars(select(ApiCall).where(
                ApiCall.job_id == self.claim.id, ApiCall.endpoint == endpoint,
            ).order_by(ApiCall.attempt.desc())).first()
            if previous and previous.details["identity"] != identity:
                raise NonRetryableError("送信済み入力または料金版が変更されています")
            if previous and previous.state in {"sent", "settled", "unknown"}:
                call_id, path = previous.id, Path(previous.response_path)
                if not path.is_file():
                    previous.state = "unknown"
                    budget.stopped = True
                recovered = True
            else:
                if previous and previous.state == "stopped":
                    raise NonRetryableError("API台帳は停止済みです")
                if previous and previous.details.get("retry_at"):
                    delay = (datetime.fromisoformat(previous.details["retry_at"])
                             - datetime.now(UTC)).total_seconds()
                    if delay > 0:
                        raise WaitForSend(delay)
                attempt = previous.attempt + 1 if previous else 1
                if (budget.stopped or budget.pricing != PRICING or attempt > 3
                        or not 0 < budget.cap_nusd <= 50 * NUSD):
                    raise NonRetryableError("API予算・料金版または試行上限により停止しました")
                if session.scalar(select(ApiCall.id).where(
                    ApiCall.budget_key == budget.key, ApiCall.state == "sent",
                ).limit(1)):
                    raise WaitForSend(30)
                used = session.scalar(select(func.coalesce(func.sum(func.coalesce(
                    ApiCall.cost_nusd, ApiCall.reserved_nusd,
                )), 0)).where(ApiCall.budget_key == budget.key))
                if reserved < 0 or used + reserved > budget.cap_nusd:
                    raise NonRetryableError("API費用上限を超える予約は送信できません")
                call_id = uuid.uuid4()
                path = Path(payload["artifact_dir"]) / f"{call_id}.json"
                retention.lock(session)
                retention.register_file(session, self.claim.asset_id, payload["host"],
                                        path, "derived")
                retention.register_file(session, self.claim.asset_id, payload["host"],
                                        path.with_suffix(".pending"), "derived")
                session.add(ApiCall(id=call_id, budget_key=budget.key, job_id=self.claim.id,
                                    endpoint=endpoint, attempt=attempt,
                                    input_hash=payload["identity_hash"], state="sent",
                                    reserved_nusd=reserved, response_path=str(path),
                                    details={"identity": identity}))
        if not recovered:
            # 予約のcommit後にだけ送る。中断位置が不明なら次回は保留する。
            with self.queue._transaction() as session:
                self.queue._owned(session, self.claim)
                self.check(session)
            try:
                envelope = request(endpoint, body, key)
                save_private(path, envelope)
            except Exception:
                with self.queue._transaction() as session:
                    budget = session.scalars(select(ApiBudget).where(
                        ApiBudget.key == payload["budget_key"],
                    ).with_for_update()).one()
                    session.get(ApiCall, call_id).state = "unknown"
                    budget.stopped = True
                raise NonRetryableError(
                    "APIの課金・完了が不明なため自動再送を停止しました",
                ) from None
        if not path.is_file():
            raise NonRetryableError("保存応答がない送信済み要求は再送できません")
        envelope = json.loads(path.read_text(encoding="utf-8"))
        response_hash = digest(envelope)
        try:
            result = json.loads(envelope["body"])
        except (ValueError, TypeError):
            result = {}
        if not isinstance(result, dict):
            result = {}
        status = envelope["status"]
        cost = 0 if endpoint.endswith("input_tokens") and status == 200 else usage_cost(
            result.get("usage"),
            cache_ttl=(body.get("prompt_cache_options") or {}).get("ttl", "30m"),
        )
        if endpoint == "responses" and (
            result.get("model") != body["model"]
            or result.get("service_tier", "default") != "default"
        ):
            cost = None
        retry = False
        with self.queue._transaction() as session:
            budget = session.scalars(select(ApiBudget).where(
                ApiBudget.key == payload["budget_key"],
            ).with_for_update()).one()
            call = session.get(ApiCall, call_id)
            if call.response_hash and call.response_hash != response_hash:
                raise NonRetryableError("保存API応答のhashが一致しません")
            if call.state != "settled":
                call.response_hash = response_hash
                call.cost_nusd = cost
                call.details = {**call.details, "request_id": envelope["request_id"],
                                "usage": result.get("usage"), "status": status,
                                "response_id": result.get("id"),
                                "returned_model": result.get("model"),
                                "returned_effort": (result.get("reasoning") or {}).get("effort")}
                if cost is not None and cost > call.reserved_nusd:
                    budget.stopped = True
                code = (result.get("error") or {}).get("code")
                transient = status == 429 or 500 <= status <= 599
                terminal = status in {401, 403} or code in {
                    "insufficient_quota", "billing_hard_limit_reached", "invalid_api_key",
                }
                if status != 200:
                    budget.failures += 1
                    retry = transient and not terminal and call.attempt < 3
                    budget.stopped = budget.stopped or terminal or budget.failures >= 2
                    retry = retry and not budget.stopped
                    call.state = "retry" if retry else "stopped"
                    call.details = {**call.details, "retry_at": (
                        datetime.now(UTC) + timedelta(seconds=retry_delay(envelope["retry_after"]))
                    ).isoformat()}
                else:
                    call.state = "settled" if cost is not None else "unknown"
                    if endpoint == "responses" and cost is not None:
                        budget.failures = 0
                    budget.stopped = budget.stopped or cost is None
        if retry:
            raise RetryLater(retry_delay(envelope["retry_after"]))
        if status != 200 or cost is None or cost > reserved:
            raise NonRetryableError("APIエラーまたは課金不明のため画像判定を停止しました")
        return result, {"call_id": str(call_id), "response_path": str(path),
                        "response_hash": response_hash, "request_id": envelope["request_id"],
                        "cost_nusd": cost, "usage": result.get("usage")}
