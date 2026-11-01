"""Openverse API を使う画像検索アダプター。"""

import json
import shutil
from pathlib import Path
from time import monotonic, sleep
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from colorstats.collect import Candidate, SearchResult
from colorstats.collect.policy import check_policy, license_class

ENDPOINT = "https://api.openverse.org/v1/images/"
MIME_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "tif": "image/tiff",
    "tiff": "image/tiff",
    "gif": "image/gif",
    "svg": "image/svg+xml",
}


class OpenverseAdapter:
    """匿名 Openverse API で検索し、元サイトのページを照合してから取得する。"""

    def __init__(self, policy, *, opener=urlopen, clock=monotonic, wait=sleep):
        check_policy(policy)
        self.policy, self.opener, self.clock, self.wait = policy, opener, clock, wait
        self.next_request = 0.0

    def _get(self, url, *, target=None, text=False):
        self.wait(max(0, self.next_request - self.clock()))
        request = Request(url, headers={"User-Agent": self.policy["user_agent"]})
        try:
            with self.opener(request, timeout=60) as response:
                if target is not None:
                    with target.open("wb") as output:
                        shutil.copyfileobj(response, output)
                    length = response.headers.get("Content-Length")
                    if length is not None and target.stat().st_size != int(length):
                        raise OSError("画像の受信が途中で終了しました")
                    return None
                if text:
                    return response.read().decode("utf-8", errors="replace")
                return json.load(response)
        finally:
            self.next_request = self.clock() + self.policy["min_interval"]

    def search(self, request):
        if request.provider != "openverse":
            raise ValueError("Openverse 以外の検索リクエストです")
        api_page = request.start // request.limit + 1
        params = {
            "q": request.query,
            "page": api_page,
            "page_size": request.limit,
            "license": "cc0,pdm,by,by-sa",
            "mature": "false",
        }
        data = self._get(ENDPOINT + "?" + urlencode(params))
        candidates = []
        for index, item in enumerate(data.get("results", [])):
            landing = item.get("foreign_landing_url") or ""
            media = item.get("url") or ""
            license_name = (item.get("license") or "").lower()
            creator = item.get("creator") or None
            license_url = item.get("license_url") or None
            filetype = item.get("filetype") or Path(urlsplit(media).path).suffix.lstrip(".")
            reasons = []
            if urlsplit(landing).scheme != "https" or not urlsplit(landing).netloc:
                reasons.append("invalid_source_url")
            if urlsplit(media).scheme != "https" or not urlsplit(media).netloc:
                reasons.append("invalid_original_url")
            if not creator:
                reasons.append("missing_author")
            if not license_url:
                reasons.append("missing_license_url")
            verified = False
            if not reasons:
                try:
                    page = self._get(landing, text=True).lower()
                    verified = license_name in page and creator.lower() in page
                except Exception:
                    verified = False
                if not verified:
                    reasons.append("source_license_or_author_unverified")
            attribution = " | ".join(
                filter(
                    None,
                    [creator, landing, item.get("license"), license_url, "変更の有無を明記"],
                )
            )
            candidates.append(
                Candidate(
                    source_url=landing,
                    original_url=media,
                    rank=request.start + index,
                    page=request.page,
                    title=item.get("title") or "",
                    author=creator,
                    license=license_name or "unknown",
                    license_url=license_url,
                    description=item.get("description"),
                    location=None,
                    width=item.get("width") or 0,
                    height=item.get("height") or 0,
                    mime=MIME_TYPES.get(filetype.lower(), filetype),
                    metadata={"openverse": item, "source_verified": verified},
                    attribution=attribution,
                    exclusion_reason=",".join(reasons) or None,
                )
            )
        effective = {
            **params,
            "endpoint": ENDPOINT,
            "api": "Openverse API v1",
            "rank_basis": {
                "base": 0,
                "scope": "search",
                "calculation": "request.start + index",
            },
            "page_basis": {"base": 0, "value": request.start, "api_value": api_page},
        }
        end = request.start + len(data.get("results", []))
        next_offset = end if data.get("result_count", 0) > end else None
        return SearchResult(candidates, effective, next_offset)

    def download(self, candidate, target: Path):
        if candidate.exclusion_reason or not candidate.metadata.get("source_verified"):
            raise ValueError(candidate.exclusion_reason or "source_license_or_author_unverified")
        if license_class(self.policy, candidate.license) == "restricted":
            raise ValueError("restricted の候補は取得できません")
        self._get(candidate.original_url, target=target)

    def finish(self):
        self.wait(max(0, self.next_request - self.clock()))
