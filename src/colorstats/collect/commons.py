"""Commons Action APIでファイルを検索し、原本とメタデータを取得する。"""

import json
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from time import monotonic, sleep
from urllib.parse import urlencode

from colorstats.collect import Candidate, SearchRequest, SearchResult
from colorstats.collect.http import HttpClient, RetryResponse
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


class CommonsAdapter(HttpClient):
    """単一スロットで直列に呼び、通信終了後の取得間隔を制限する。

    HTTP 429/503とAPI負荷制限はRetry-Afterと指数待機を尊重する。
    openerはurllib互換で、記録済みレスポンスをテストに注入できる。
    """

    def __init__(self, policy: dict, *, opener=None, clock=monotonic, wait=sleep):
        check_commons_policy(policy)
        super().__init__(policy, opener=opener, clock=clock, wait=wait)

    def _get(self, url: str, *, target: Path | None = None):
        check_commons_policy(self.policy)
        return self.get(url, target=target, read=self._read, api=target is None)

    @staticmethod
    def _read(response):
        data = json.load(response)
        error = data.get("error")
        if error is None:
            return data
        if error.get("code") not in ("maxlag", "ratelimited", "cirrussearch-too-busy-error"):
            raise RuntimeError(f"Commons APIエラー: {error.get('code')}")
        raise RetryResponse(response.headers)

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
            "srsearch": (
                f"{request.query} filetype:bitmap -intitle:canvas -intitle:painting"
            ),
            "srlimit": request.limit,
            "sroffset": request.start,
            "srsort": "relevance",
            "srwhat": "text",
            "srqiprofile": "classic",
            "uselang": request.language,
        }
        effective = {
            "download_mode": request.download_mode,
            **parameters,
            "endpoint": ENDPOINT,
            "api": "MediaWiki Action API",
            "defaults": {"srinterwiki": False, "srenablerewrites": False},
            "rank_basis": {"base": 0, "scope": "search", "calculation": "sroffset + index"},
            "page_basis": {"base": 0, "value": request.page, "origin": "SearchRequest.page"},
        }
        self.observe("search", {"effective": effective})
        search = self._get(ENDPOINT + "?" + urlencode(parameters))
        next_offset = search.get("continue", {}).get("sroffset")
        self.observe("search", {"api_next_offset": next_offset})
        self.observe("search", {"api_results": search.get("query", {}).get("search", [])})
        candidates = []
        for index, hit in enumerate(search.get("query", {}).get("search", [])):
            self.observe("search", {"pending_candidate": {**hit, "rank": request.start + index}})
            metadata_parameters = {
                "action": "query",
                "format": "json",
                "formatversion": 2,
                "maxlag": self.policy["maxlag"],
                "pageids": hit["pageid"],
                "prop": "imageinfo|categories",
                "cllimit": "max",
                "iiprop": "url|size|mime|sha1|timestamp|extmetadata",
                "iiextmetadatalanguage": request.language,
            }
            if request.download_mode == "thumbnail":
                metadata_parameters["iiurlwidth"] = 1280
                metadata_parameters["iiprop"] += "|thumbmime"
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
                        "API縮小・再圧縮の可能性あり"
                        if request.download_mode == "thumbnail" else "原本・改変なし",
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
            rendition = {
                "provider": request.provider,
                "native_id": str(hit["pageid"]),
                "revision": info.get("timestamp"),
                "variant": request.download_mode,
                "original": {
                    "url": info["url"], "width": info["width"], "height": info["height"],
                    "mime": info["mime"], "sha1": info.get("sha1"), "sha256": None,
                },
            }
            download_url = None
            rendition_reason = None
            if request.download_mode == "thumbnail":
                download_url = info.get("thumburl")
                rendition.update(
                    requested_width=1280, width=info.get("thumbwidth"),
                    height=info.get("thumbheight"), mime=info.get("thumbmime"),
                )
                if info["width"] <= 1280:
                    rendition_reason = "thumbnail_not_smaller"
                elif not download_url or not all(
                    rendition.get(key) for key in ("width", "height", "mime")
                ):
                    rendition_reason = "thumbnail_missing"
                elif not rendition["revision"]:
                    rendition_reason = "thumbnail_revision_missing"
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
                    else rendition_reason,
                    download_url=download_url,
                    rendition=rendition,
                )
            )
            self.record_candidate(candidates[-1], verified=not candidates[-1].exclusion_reason)

        return SearchResult(candidates, effective, next_offset)

    def download(self, candidate: Candidate, target: Path) -> None:
        if license_class(self.policy, candidate.license) == "restricted":
            raise ValueError("restrictedの原本は取得しません")
        if candidate.exclusion_reason:
            raise ValueError(candidate.exclusion_reason)
        if candidate.rendition.get("variant") == "thumbnail" and not candidate.download_url:
            raise ValueError("thumbnail_missing")
        self._get(candidate.download_url or candidate.original_url, target=target)
