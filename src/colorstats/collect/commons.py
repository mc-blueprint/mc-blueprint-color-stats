"""Commons Action APIでファイルを検索し、原本とメタデータを取得する。"""

import json
import shutil
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from colorstats.collect import Candidate, SearchRequest, SearchResult
from colorstats.collect.policy import check_policy, license_class

ENDPOINT = "https://commons.wikimedia.org/w/api.php"


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _text(value: str) -> str:
    parser = _Text()
    parser.feed(value)
    return unescape(" ".join(parser.parts)).strip()


def check_commons_policy(policy: dict) -> None:
    """共通設定に加え、Commons固有の負荷制限を通信前に検証する。"""
    check_policy(policy)
    if policy.get("maxlag", 0) <= 0:
        raise ValueError("正のmaxlagが必要です")


class CommonsAdapter:
    """単一スロットで直列に呼び、通信終了後の取得間隔を制限する。

    HTTP 429/503とAPI maxlag/ratelimitedはRetry-Afterと指数待機を尊重する。
    openerはurllib互換で、記録済みレスポンスをテストに注入できる。
    """

    def __init__(self, policy: dict, *, opener=urlopen, clock=monotonic, wait=sleep):
        check_commons_policy(policy)
        self.policy = policy
        self.opener = opener
        self.clock = clock
        self.wait = wait
        self.next_request = 0.0

    def _delay(self, headers, attempt):
        delay = self.policy["backoff"] * 2**attempt
        value = headers.get("Retry-After")
        if value:
            try:
                seconds = float(value)
            except ValueError:
                seconds = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
            delay = max(delay, seconds)
        self.next_request = max(self.next_request, self.clock() + delay)

    def _get(self, url: str, *, target: Path | None = None):
        check_commons_policy(self.policy)
        for attempt in range(self.policy["retries"] + 1):
            self.wait(max(0, self.next_request - self.clock()))
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
                    data = json.load(response)
                    error = data.get("error")
                    if error is None:
                        return data
                    if error.get("code") not in ("maxlag", "ratelimited"):
                        raise RuntimeError(f"Commons APIエラー: {error.get('code')}")
                    self._delay(response.headers, attempt)
            except HTTPError as error:
                if error.code not in (429, 503):
                    raise
                self._delay(error.headers, attempt)
                error.close()
            finally:
                self.next_request = max(
                    self.next_request, self.clock() + self.policy["min_interval"]
                )
        # 最終試行の指示も守り、次のキュージョブによる即時再試行を防ぐ。
        self.wait(max(0, self.next_request - self.clock()))
        raise RuntimeError("Commonsの負荷制限により取得を中断しました")

    def search(self, request: SearchRequest) -> SearchResult:
        if request.provider != "wikimedia_commons":
            raise ValueError("Commons以外の検索リクエストです")
        parameters = {
            "action": "query",
            "format": "json",
            "formatversion": 2,
            "maxlag": self.policy["maxlag"],
            "list": "search",
            "srnamespace": 6,
            "srsearch": request.query,
            "srlimit": request.limit,
            "sroffset": request.start,
            "srsort": "relevance",
            "srwhat": "text",
            "srqiprofile": "classic",
            "uselang": request.language,
        }
        search = self._get(ENDPOINT + "?" + urlencode(parameters))
        candidates = []
        for index, hit in enumerate(search.get("query", {}).get("search", [])):
            metadata_parameters = {
                "action": "query",
                "format": "json",
                "formatversion": 2,
                "maxlag": self.policy["maxlag"],
                "pageids": hit["pageid"],
                "prop": "imageinfo|categories",
                "cllimit": "max",
                "iiprop": "url|size|mime|extmetadata",
                "iiextmetadatalanguage": request.language,
            }
            response = self._get(ENDPOINT + "?" + urlencode(metadata_parameters))
            pages = response.get("query", {}).get("pages", [])
            if not pages or not pages[0].get("imageinfo"):
                continue
            info = pages[0]["imageinfo"][0]
            categories = list(pages[0].get("categories", []))
            while "clcontinue" in response.get("continue", {}):
                response = self._get(
                    ENDPOINT
                    + "?"
                    + urlencode(
                        {
                            "action": "query",
                            "format": "json",
                            "formatversion": 2,
                            "maxlag": self.policy["maxlag"],
                            "pageids": hit["pageid"],
                            "prop": "categories",
                            "cllimit": "max",
                            "clcontinue": response["continue"]["clcontinue"],
                            "continue": response["continue"]["continue"],
                        }
                    )
                )
                for page in response.get("query", {}).get("pages", []):
                    categories.extend(page.get("categories", []))
            if not info.get("mime", "").startswith("image/"):
                continue
            if info.get("width", 0) <= 0 or info.get("height", 0) <= 0:
                continue
            ext = info.get("extmetadata", {})

            def value(key, ext=ext):
                return _text(ext.get(key, {}).get("value", "")) or None

            latitude, longitude = value("GPSLatitude"), value("GPSLongitude")
            location = f"{latitude}, {longitude}" if latitude and longitude else value("Location")
            author = value("Artist")
            specified = value("Attribution")
            license_name = value("License") or "unknown"
            short_name = value("LicenseShortName")
            license_url = value("LicenseUrl")
            required = (
                license_name.lower().startswith("cc-by-")
                or (value("AttributionRequired") or "").lower() == "true"
            )
            missing = []
            if required:
                if not (author or specified):
                    missing.append("author_or_attribution")
                if not short_name:
                    missing.append("license_name")
                if not license_url:
                    missing.append("license_url")
            credit = [specified] if specified else [author, value("Credit")]
            attribution = " | ".join(
                filter(
                    None,
                    [
                        *credit,
                        info["descriptionurl"],
                        short_name or license_name,
                        license_url,
                        "原本・改変なし",
                    ],
                )
            )
            selection = {
                "method": "CommonsMetadata",
                "selected": license_name,
                "candidates": [
                    category["title"]
                    for category in categories
                    if category["title"]
                    .lower()
                    .startswith(("category:cc-", "category:cc0", "category:pd-", "category:gfdl"))
                ],
                "candidate_basis": "Commons license categories",
            }
            candidates.append(
                Candidate(
                    source_url=info["descriptionurl"],
                    original_url=info["url"],
                    rank=request.start + index,
                    page=request.page,
                    title=hit["title"],
                    author=author,
                    license=license_name,
                    license_url=license_url,
                    description=value("ImageDescription"),
                    location=location,
                    width=info["width"],
                    height=info["height"],
                    mime=info["mime"],
                    metadata={**info, "categories": categories, "license_selection": selection},
                    attribution=attribution,
                    exclusion_reason="missing_attribution:" + ",".join(missing)
                    if missing
                    else None,
                )
            )
        effective = {
            **parameters,
            "endpoint": ENDPOINT,
            "api": "MediaWiki Action API",
            "defaults": {"srinterwiki": False, "srenablerewrites": False},
            "rank_basis": {"base": 0, "scope": "search", "calculation": "sroffset + index"},
            "page_basis": {"base": 0, "value": request.page, "origin": "SearchRequest.page"},
        }
        return SearchResult(candidates, effective, search.get("continue", {}).get("sroffset"))

    def download(self, candidate: Candidate, target: Path) -> None:
        if license_class(self.policy, candidate.license) == "restricted":
            raise ValueError("restrictedの原本は取得しません")
        if candidate.exclusion_reason:
            raise ValueError(candidate.exclusion_reason)
        self._get(candidate.original_url, target=target)

    def finish(self) -> None:
        """次ジョブが別プロセスでも取得間隔を保つため、残りの待機を済ませる。"""
        self.wait(max(0, self.next_request - self.clock()))
