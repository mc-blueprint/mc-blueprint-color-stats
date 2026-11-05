"""収集先に共通する直列HTTP取得と負荷待機。"""

import json
from collections import deque
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from threading import BoundedSemaphore, Lock
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from colorstats.collect.policy import check_policy

_HOST_STATES = {}
_HOST_STATES_LOCK = Lock()


def _host_state(host, max_concurrency=1):
    with _HOST_STATES_LOCK:
        return _HOST_STATES.setdefault(
            host,
            {
                "next_request": 0.0,
                "backoff_until": 0.0,
                "api_requests": deque(),
                "media_window": deque(),
                "media_bytes": 0,
                "media_lock": Lock(),
                "schedule_lock": Lock(),
                "semaphore": BoundedSemaphore(max_concurrency),
            },
        )


class MeasurementLimit(RuntimeError):
    """事前固定した通信枠を使い切った。追加の通信は行わない。"""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _CountingResponse:
    def __init__(self, response, clock):
        self.response = response
        self.clock = clock
        self.bytes = 0
        self.network_seconds = 0.0

    def read(self, *args):
        started = self.clock()
        try:
            data = self.response.read(*args)
        finally:
            self.network_seconds += max(0.0, self.clock() - started)
        self.bytes += len(data)
        return data

    def __getattr__(self, name):
        return getattr(self.response, name)


class HttpClient:
    """429/503では再試行し、終了時も取得間隔とRetry-Afterを守る。

    readは応答の処理関数。provider固有の負荷制限ではRetryResponseを送出する。
    その他の例外は再試行せず呼出し元へ伝播する。
    """

    def __init__(self, policy, *, opener=None, clock=monotonic, wait=sleep):
        check_policy(policy)
        self.policy, self.clock, self.wait = policy, clock, wait
        self.opener = opener if opener is not None else build_opener(_NoRedirect()).open
        self.observer = None
        self.quota_reserve = None
        self.hosts_used = set()

    def observe(self, event, value=1):
        if self.observer is not None:
            self.observer(event, self._safe_value(value))

    @classmethod
    def _safe_value(cls, value):
        if isinstance(value, dict):
            return {
                key: "[redacted]" if cls._secret_query_key(str(key)) else cls._safe_value(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls._safe_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(cls._safe_value(item) for item in value)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return cls._without_secret_query(value)
        return value

    @classmethod
    def _without_secret_query(cls, url):
        parts = urlsplit(url)
        query = [
            (key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
            if not cls._secret_query_key(key)
        ]
        netloc = parts.netloc.rsplit("@", 1)[-1]
        return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query), ""))

    @staticmethod
    def _secret_query_key(key):
        key = key.casefold()
        return (
            key in {
                "key", "sig", "signature", "credential", "password", "auth", "authorization",
            }
            or any(
                token in key
                for token in ("token", "secret", "api_key", "apikey", "access_key", "accesskey")
            )
            or key.startswith(("x-amz-", "x-goog-"))
        )

    def record_candidate(self, candidate, *, verified):
        """照合結果とURL・順位・除外理由を、検索完了前にobserverへ渡す。"""
        self.observe("candidate", {
            "source_url": candidate.source_url, "original_url": candidate.original_url,
            "rank": candidate.rank, "reason": candidate.exclusion_reason, "verified": verified,
        })

    def _delay(self, headers, attempt, url):
        delay = self.policy["backoff"] * 2**attempt
        value = headers.get("Retry-After")
        if value:
            try:
                seconds = float(value)
            except ValueError:
                try:
                    seconds = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    seconds = 0
            delay = max(delay, seconds)
        host = urlsplit(url).hostname.lower().rstrip(".")
        state = _host_state(host)
        state["backoff_until"] = max(state["backoff_until"], self.clock() + delay)

    def _observe_wait(self, event, delay):
        if delay > 0:
            self.observe(event, delay)

    def _host_policy(self, url):
        parts = urlsplit(url)
        if parts.username or parts.password:
            raise ValueError("URL埋め込み認証を拒否しました")
        host = (parts.hostname or "").lower().rstrip(".")
        for suffix, config in self.policy.get("hosts", {}).items():
            suffix = suffix.lower().lstrip(".")
            if host == suffix or host.endswith("." + suffix):
                path = unquote(parts.path).casefold()
                if any(
                    blocked.casefold() in path for blocked in config.get("disallow_paths", [])
                ):
                    raise ValueError("source_policyで禁止されたpathです")
                return config
        raise ValueError("source_policy未登録の接続先です")

    def _error_bytes(self, error, *, media=False, state=None, host_policy=None):
        if error.fp is None:
            return 0
        if not media:
            return len(error.read())
        total = 0
        while chunk := self._read_media(error, state, host_policy):
            total += len(chunk)
            self._record_media(len(chunk), state)
        return total

    def _wait_for_slot(self, url):
        host_policy = self._host_policy(url)
        kind = host_policy["kind"]
        interval = host_policy.get(
            "min_interval",
            self.policy.get(f"{kind}_min_interval", self.policy["min_interval"]),
        )
        host_name = (urlsplit(url).hostname or "").lower().rstrip(".")
        state = _host_state(host_name, host_policy.get("max_concurrency", 1))
        state["media_limit"] = host_policy.get(
            "media_bytes_per_10_seconds", self.policy.get("media_bytes_per_10_seconds")
        )
        self.hosts_used.add(host_name)
        with state["schedule_lock"]:
            now = self.clock()
            normal_due = state["next_request"]
            if kind == "api":
                windows = host_policy.get("api_windows", self.policy.get("api_windows", []))
                for window in windows:
                    recent = [
                        timestamp for timestamp in state["api_requests"]
                        if timestamp > now - window["seconds"]
                    ]
                    if len(recent) >= window["limit"]:
                        normal_due = max(normal_due, recent[0] + window["seconds"])
                if windows:
                    oldest = now - max(window["seconds"] for window in windows)
                    while state["api_requests"] and state["api_requests"][0] <= oldest:
                        state["api_requests"].popleft()
            backoff_due = state["backoff_until"]
            total_delay = max(0.0, max(normal_due, backoff_due) - now)
            backoff_delay = min(total_delay, max(0.0, backoff_due - now))
            normal_delay = total_delay - backoff_delay
            self._observe_wait("normal_wait_seconds", normal_delay)
            self._observe_wait("backoff_seconds", backoff_delay)
            if normal_delay + backoff_delay:
                self.wait(normal_delay + backoff_delay)
            slot_time = self.clock()
            state["next_request"] = max(state["next_request"], slot_time + interval)
            if kind == "api":
                state["api_requests"].append(slot_time)
        return kind, interval, host_name, host_policy, state

    def get(self, url, *, target=None, text=False, read=json.load, api=False):
        """JSON・テキストを返すか、試行専用targetへ原本を書き込む。

        api=Trueは追従先と再試行もAPI枠へ計上する。openerはリダイレクトを追従しないもの。
        """
        check_policy(self.policy)
        for attempt in range(self.policy["retries"] + 1):
            current, redirects = url, 0
            while True:
                check_policy(self.policy)
                kind, interval, host_name, host_policy, state = self._wait_for_slot(current)
                self.observe("api_request" if kind == "api" else "request")
                if kind == "api" and self.quota_reserve is not None:
                    windows = host_policy.get(
                        "api_windows", self.policy.get("api_windows", [])
                    )
                    while delay := self.quota_reserve(host_name, kind, windows):
                        self._observe_wait("normal_wait_seconds", delay)
                        self.wait(delay)
                state["semaphore"].acquire()
                acquired = True
                counted = None
                started = self.clock()
                network_seconds = 0.0
                try:
                    request = Request(current, headers={"User-Agent": self.policy["user_agent"]})
                    open_started = self.clock()
                    with self.opener(request, timeout=60) as response:
                        network_seconds += max(0.0, self.clock() - open_started)
                        self.observe("responses")
                        counted = response = _CountingResponse(response, self.clock)
                        if target is not None:
                            with target.open("wb") as output:
                                while chunk := self._read_media(response, state, host_policy):
                                    output.write(chunk)
                            length = response.headers.get("Content-Length")
                            if length is not None and target.stat().st_size != int(length):
                                raise OSError("原本の受信が途中で終了しました")
                            return None
                        if text:
                            return response.read().decode("utf-8", errors="replace")
                        return read(response)
                except HTTPError as error:
                    network_seconds += max(0.0, self.clock() - started)
                    self.observe("responses")
                    if error.code in (301, 302, 303, 307, 308):
                        try:
                            received = self._error_bytes(
                                error, media=kind == "media", state=state, host_policy=host_policy
                            )
                            self.observe("bytes", received)
                            target_url = urljoin(current, error.headers.get("Location", ""))
                            source_host = (urlsplit(current).hostname or "").casefold()
                            target_host = (urlsplit(target_url).hostname or "").casefold()
                            if target_host != source_host:
                                target_url = self._without_secret_query(target_url)
                        finally:
                            error.close()
                        redirects += 1
                        if redirects > 10 or urlsplit(target_url).scheme not in ("http", "https"):
                            raise RuntimeError("リダイレクトを中断しました") from None
                        self._host_policy(target_url)
                        current = target_url
                        continue
                    if error.code not in (429, 503):
                        self.observe("bytes", self._error_bytes(
                            error, media=kind == "media", state=state, host_policy=host_policy
                        ))
                        raise
                    self.observe("bytes", self._error_bytes(
                        error, media=kind == "media", state=state, host_policy=host_policy
                    ))
                    self._delay(error.headers, attempt, current)
                    error.close()
                    break
                except RetryResponse as error:
                    self._delay(error.headers, attempt, current)
                    break
                except (TimeoutError, URLError) as error:
                    if isinstance(error, TimeoutError) or isinstance(error.reason, TimeoutError):
                        self.observe("timeouts")
                    raise
                finally:
                    elapsed = max(0.0, self.clock() - started)
                    if counted is not None:
                        self.observe("bytes", counted.bytes)
                        network_seconds += counted.network_seconds
                    else:
                        network_seconds = max(network_seconds, elapsed)
                    self.observe(f"network_{kind}_seconds", network_seconds)
                    cooldown = host_policy.get(
                        f"{kind}_slow_seconds", self.policy.get(f"{kind}_slow_seconds", 0)
                    )
                    delay = cooldown if kind == "api" and network_seconds > 1.0 else interval
                    state["next_request"] = max(state["next_request"], self.clock() + delay)
                    if acquired:
                        state["semaphore"].release()

        self.finish()
        raise RuntimeError("負荷制限により取得を中断しました")

    def _media_chunk_size(self, state, host_policy):
        limit = host_policy.get(
            "media_bytes_per_10_seconds", self.policy.get("media_bytes_per_10_seconds")
        )
        if not limit:
            return 64 * 1024
        now = self.clock()
        while state["media_window"] and state["media_window"][0][0] <= now - 10:
            _, old_size = state["media_window"].popleft()
            state["media_bytes"] -= old_size
        if state["media_bytes"] >= limit:
            delay = max(0.0, state["media_window"][0][0] + 10 - now)
            self._observe_wait("bandwidth_wait_seconds", delay)
            self.wait(delay)
            now = self.clock()
            while state["media_window"] and state["media_window"][0][0] <= now - 10:
                _, old_size = state["media_window"].popleft()
                state["media_bytes"] -= old_size
        return min(64 * 1024, limit - state["media_bytes"])

    def _record_media(self, size, state):
        if not state.get("media_limit"):
            return
        now = self.clock()
        state["media_window"].append((now, size))
        state["media_bytes"] += size

    def _read_media(self, response, state, host_policy):
        with state["media_lock"]:
            chunk = response.read(self._media_chunk_size(state, host_policy))
            if chunk:
                self._record_media(len(chunk), state)
            return chunk

    def finish(self):
        """別プロセスの次ジョブにも待機を引き継ぐため、残りの待機を済ませる。"""
        now = self.clock()
        states = [_host_state(host) for host in self.hosts_used]
        normal_due = max((state["next_request"] for state in states), default=0.0)
        backoff_due = max((state["backoff_until"] for state in states), default=0.0)
        total_delay = max(0.0, max(normal_due, backoff_due) - now)
        backoff_delay = min(total_delay, max(0.0, backoff_due - now))
        normal_delay = total_delay - backoff_delay
        self._observe_wait("normal_wait_seconds", normal_delay)
        self._observe_wait("backoff_seconds", backoff_delay)
        self.wait(normal_delay + backoff_delay)


class RetryResponse(Exception):
    """HTTP成功応答内のprovider固有の負荷制限を共通再試行へ渡す。"""

    def __init__(self, headers):
        super().__init__("API負荷制限")
        self.headers = headers
