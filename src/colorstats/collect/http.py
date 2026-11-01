"""収集先に共通する直列HTTP取得と負荷待機。"""

import json
import shutil
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from colorstats.collect.policy import check_policy


class HttpClient:
    """429/503では再試行し、終了時も取得間隔とRetry-Afterを守る。

    readは応答の処理関数。provider固有の負荷制限ではRetryResponseを送出する。
    その他の例外は再試行せず呼出し元へ伝播する。
    """

    def __init__(self, policy, *, opener=urlopen, clock=monotonic, wait=sleep):
        check_policy(policy)
        self.policy, self.opener, self.clock, self.wait = policy, opener, clock, wait
        self.next_request = 0.0

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

    def get(self, url, *, target=None, text=False, read=json.load):
        """JSON・テキストを返すか、試行専用targetへ原本を書き込む。"""
        check_policy(self.policy)
        for attempt in range(self.policy["retries"] + 1):
            self.finish()
            try:
                request = Request(url, headers={"User-Agent": self.policy["user_agent"]})
                with self.opener(request, timeout=60) as response:
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
                if error.code not in (429, 503):
                    raise
                self._delay(error.headers, attempt)
                error.close()
            except RetryResponse as error:
                self._delay(error.headers, attempt)
            finally:
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
