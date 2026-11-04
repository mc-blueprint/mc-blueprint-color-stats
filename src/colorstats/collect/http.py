"""収集先に共通する直列HTTP取得と負荷待機。"""

import json
import shutil
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from colorstats.collect.policy import check_policy


class MeasurementLimit(RuntimeError):
    """事前固定した通信枠を使い切った。追加の通信は行わない。"""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _CountingResponse:
    def __init__(self, response):
        self.response = response
        self.bytes = 0

    def read(self, *args):
        data = self.response.read(*args)
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
        self.observer = None

    def observe(self, event, value=1):
        if self.observer is not None:
            self.observer(event, value)

    def record_candidate(self, candidate, *, verified):
        """照合結果とURL・順位・除外理由を、検索完了前にobserverへ渡す。"""
        self.observe("candidate", {
            "source_url": candidate.source_url, "original_url": candidate.original_url,
            "rank": candidate.rank, "reason": candidate.exclusion_reason, "verified": verified,
        })

    def _delay(self, headers, attempt):
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
        self.next_request = max(self.next_request, self.clock() + delay)

    def get(self, url, *, target=None, text=False, read=json.load, api=False):
        """JSON・テキストを返すか、試行専用targetへ原本を書き込む。

        api=Trueは追従先と再試行もAPI枠へ計上する。openerはリダイレクトを追従しないもの。
        """
        check_policy(self.policy)
        for attempt in range(self.policy["retries"] + 1):
            current, redirects = url, 0
            while True:
                check_policy(self.policy)
                self.finish()
                self.observe("api_request" if api else "request")
                counted = None
                try:
                    request = Request(current, headers={"User-Agent": self.policy["user_agent"]})
                    with self.opener(request, timeout=60) as response:
                        self.observe("responses")
                        counted = response = _CountingResponse(response)
                        if target is not None:
                            with target.open("wb") as output:
                                shutil.copyfileobj(response, output)
                            length = response.headers.get("Content-Length")
                            if length is not None and target.stat().st_size != int(length):
                                raise OSError("原本の受信が途中で終了しました")
                            return None
                        if text:
                            return response.read().decode("utf-8", errors="replace")
                        return read(response)
                except HTTPError as error:
                    self.observe("responses")
                    if error.code in (301, 302, 303, 307, 308):
                        try:
                            self.observe("bytes", len(error.read()))
                            target_url = urljoin(current, error.headers.get("Location", ""))
                        finally:
                            error.close()
                        redirects += 1
                        if redirects > 10 or urlsplit(target_url).scheme not in ("http", "https"):
                            raise RuntimeError("リダイレクトを中断しました") from None
                        current = target_url
                        continue
                    if error.code not in (429, 503):
                        raise
                    self._delay(error.headers, attempt)
                    error.close()
                    break
                except RetryResponse as error:
                    self._delay(error.headers, attempt)
                    break
                except (TimeoutError, URLError) as error:
                    if isinstance(error, TimeoutError) or isinstance(error.reason, TimeoutError):
                        self.observe("timeouts")
                    raise
                finally:
                    if counted is not None:
                        self.observe("bytes", counted.bytes)
                    self.next_request = max(
                        self.next_request, self.clock() + self.policy["min_interval"]
                    )
        self.finish()
        raise RuntimeError("負荷制限により取得を中断しました")

    def finish(self):
        """別プロセスの次ジョブにも待機を引き継ぐため、残りの待機を済ませる。"""
        self.wait(max(0, self.next_request - self.clock()))


class RetryResponse(Exception):
    """HTTP成功応答内のprovider固有の負荷制限を共通再試行へ渡す。"""

    def __init__(self, headers):
        super().__init__("API負荷制限")
        self.headers = headers
