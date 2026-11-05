"""収集先に共通する直列HTTP取得と負荷待機。"""

import json
from collections import deque
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from colorstats.collect.policy import check_policy


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
        data = self.response.read(*args)
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
        self.next_request = 0.0
        self.next_api_request = 0.0
        self.next_media_request = 0.0
        self.next_host_request = {}
        self.host_backoff_until = {}
        self.media_window = deque()
        self.media_bytes = 0
        self.api_requests = deque()
        self.observer = None

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
            parts = urlsplit(value)
            query = [
                (key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
                if not cls._secret_query_key(key)
            ]
            netloc = parts.netloc.rsplit("@", 1)[-1]
            return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query), ""))
        return value

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
        self.host_backoff_until[host] = max(
            self.host_backoff_until.get(host, 0.0), self.clock() + delay
        )

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

    def _error_bytes(self, error, *, media=False):
        if error.fp is None:
            return 0
        if not media:
            return len(error.read())
        total = 0
        while chunk := error.read(self._media_chunk_size()):
            total += len(chunk)
            self._record_media(len(chunk))
        return total

    def _wait_for_slot(self, url, api, media):
        host = self._host_policy(url)
        kind = "api" if api else "media" if media else host.get("kind", "page")
        interval = self.policy.get(f"{kind}_min_interval", self.policy["min_interval"])
        field = f"next_{kind}_request"
        due = getattr(self, field, 0.0)
        host_name = (urlsplit(url).hostname or "").lower().rstrip(".")
        now = self.clock()
        normal_due = max(due, self.next_host_request.get(host_name, 0.0))
        if kind == "api":
            windows = self.policy.get("api_windows", [])
            for window in windows:
                recent = [t for t in self.api_requests if t > now - window["seconds"]]
                if len(recent) >= window["limit"]:
                    normal_due = max(normal_due, recent[0] + window["seconds"])
            if windows:
                oldest = now - max(window["seconds"] for window in windows)
                while self.api_requests and self.api_requests[0] <= oldest:
                    self.api_requests.popleft()
        backoff_due = self.host_backoff_until.get(host_name, 0.0)
        total_delay = max(0.0, max(normal_due, backoff_due) - now)
        backoff_delay = min(total_delay, max(0.0, backoff_due - now))
        normal_delay = total_delay - backoff_delay
        self._observe_wait("normal_wait_seconds", normal_delay)
        self._observe_wait("backoff_seconds", backoff_delay)
        if normal_delay + backoff_delay:
            self.wait(normal_delay + backoff_delay)
        if kind == "api":
            self.api_requests.append(self.clock())
        return kind, interval

    def get(self, url, *, target=None, text=False, read=json.load, api=False):
        """JSON・テキストを返すか、試行専用targetへ原本を書き込む。

        api=Trueは追従先と再試行もAPI枠へ計上する。openerはリダイレクトを追従しないもの。
        """
        check_policy(self.policy)
        for attempt in range(self.policy["retries"] + 1):
            current, redirects = url, 0
            while True:
                check_policy(self.policy)
                kind, interval = self._wait_for_slot(current, api, target is not None)
                self.observe("api_request" if api else "request")
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
                                while chunk := response.read(self._media_chunk_size()):
                                    self._record_media(len(chunk))
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
                            received = self._error_bytes(error, media=target is not None)
                            self.observe("bytes", received)
                            target_url = urljoin(current, error.headers.get("Location", ""))
                        finally:
                            error.close()
                        redirects += 1
                        if redirects > 10 or urlsplit(target_url).scheme not in ("http", "https"):
                            raise RuntimeError("リダイレクトを中断しました") from None
                        self._host_policy(target_url)
                        current = target_url
                        continue
                    if error.code not in (429, 503):
                        self.observe("bytes", self._error_bytes(error, media=target is not None))
                        raise
                    self.observe("bytes", self._error_bytes(error, media=target is not None))
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
                    if counted is None and not network_seconds:
                        network_seconds = elapsed
                    if counted is not None:
                        self.observe("bytes", counted.bytes)
                        network_seconds += counted.network_seconds
                    self.observe(f"network_{kind}_seconds", network_seconds)
                    field = f"next_{kind}_request"
                    cooldown = self.policy.get(f"{kind}_slow_seconds", 0)
                    delay = cooldown if kind == "api" and network_seconds > 1.0 else interval
                    setattr(self, field, max(getattr(self, field, 0.0), self.clock() + delay))
                    host_name = (urlsplit(current).hostname or "").lower().rstrip(".")
                    self.next_host_request[host_name] = max(
                        self.next_host_request.get(host_name, 0.0), self.clock() + delay
                    )

        self.finish()
        raise RuntimeError("負荷制限により取得を中断しました")

    def _media_chunk_size(self):
        limit = self.policy.get("media_bytes_per_10_seconds")
        if not limit:
            return 64 * 1024
        now = self.clock()
        while self.media_window and self.media_window[0][0] <= now - 10:
            _, old_size = self.media_window.popleft()
            self.media_bytes -= old_size
        if self.media_bytes >= limit:
            delay = max(0.0, self.media_window[0][0] + 10 - now)
            self._observe_wait("bandwidth_wait_seconds", delay)
            self.wait(delay)
            now = self.clock()
            while self.media_window and self.media_window[0][0] <= now - 10:
                _, old_size = self.media_window.popleft()
                self.media_bytes -= old_size
        return min(64 * 1024, limit - self.media_bytes)

    def _record_media(self, size):
        if not self.policy.get("media_bytes_per_10_seconds"):
            return
        now = self.clock()
        self.media_window.append((now, size))
        self.media_bytes += size

    def finish(self):
        """別プロセスの次ジョブにも待機を引き継ぐため、残りの待機を済ませる。"""
        now = self.clock()
        normal_due = max(
            self.next_request,
            self.next_api_request,
            self.next_media_request,
            max(self.next_host_request.values(), default=0.0),
        )
        backoff_due = max(self.host_backoff_until.values(), default=0.0)
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
