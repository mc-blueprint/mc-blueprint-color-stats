"""Openverse API を使う画像検索アダプター。"""

import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from colorstats.collect import Candidate, SearchResult
from colorstats.collect.http import HttpClient, MeasurementLimit
from colorstats.collect.policy import license_class

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


class _LinkedData(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = None
        self.documents = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type", "").lower() == "application/ld+json":
            self.parts = []

    def handle_data(self, data):
        if self.parts is not None:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.parts is not None:
            try:
                self.documents.append(json.loads("".join(self.parts)))
            except ValueError:
                pass
            self.parts = None


def _images(value, schema=False):
    if isinstance(value, list):
        for child in value:
            yield from _images(child, schema)
    elif isinstance(value, dict):
        context = value.get("@context")
        if context is not None:
            schema = context in (
                "https://schema.org", "https://schema.org/",
                "http://schema.org", "http://schema.org/",
            )
        kind = value.get("@type")
        if schema and kind in (
            "ImageObject", "https://schema.org/ImageObject", "http://schema.org/ImageObject"
        ):
            yield value
        for child in value.values():
            yield from _images(child, schema)


def _license_url(value):
    if not isinstance(value, str):
        return None
    url = urlsplit(value)
    if (
        url.scheme not in ("http", "https") or url.netloc != "creativecommons.org"
        or url.query or url.fragment
    ):
        return None
    return url.path.rstrip("/")


def _verify_source(page, item):
    """対象原本と結び付くImageObjectの作者・CCライセンスURLを完全照合する。"""
    name, version = item.get("license"), item.get("license_version")
    versions = ("1.0",) if name in ("cc0", "pdm") else ("1.0", "2.0", "2.5", "3.0", "4.0")
    if name not in ("by", "by-sa", "cc0", "pdm") or version not in versions:
        return False
    path = {"cc0": "publicdomain/zero", "pdm": "publicdomain/mark"}.get(
        name, f"licenses/{name}"
    )
    expected = f"/{path}/{version}"
    if _license_url(item.get("license_url")) != expected:
        return False
    parser = _LinkedData()
    parser.feed(page)
    matches = [
        image for document in parser.documents for image in _images(document)
        if image.get("contentUrl", image.get("url")) == item["url"]
    ]
    if not matches:
        return False
    for image in matches:
        author = image.get("creator", image.get("author"))
        if isinstance(author, dict):
            author = author.get("name")
        if (
            not isinstance(author, str)
            or author.strip().casefold() != item["creator"].strip().casefold()
        ):
            return False
        license_url = image.get("license")
        if isinstance(license_url, dict):
            license_url = license_url.get("@id", license_url.get("url"))
        if _license_url(license_url) != expected:
            return False
    return True


class OpenverseAdapter(HttpClient):
    """匿名 Openverse API で検索し、元サイトのページを照合してから取得する。"""

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
        self.observe("search", {"effective": effective})
        data = self.get(ENDPOINT + "?" + urlencode(params), api=True)
        end = request.start + len(data.get("results", []))
        next_offset = end if data.get("result_count", 0) > end else None
        self.observe("search", {"api_next_offset": next_offset})
        self.observe("search", {"api_results": data.get("results", [])})
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
            self.observe("search", {"pending_candidate": {
                "source_url": landing, "original_url": media, "rank": request.start + index,
            }})
            if not reasons:
                try:
                    page = self.get(landing, text=True)
                    verified = _verify_source(page, item)
                except MeasurementLimit as error:
                    self.observe("exclusion", {
                        "source_url": landing, "original_url": media,
                        "rank": request.start + index,
                        "reason": "verification_stopped:" + str(error),
                    })
                    raise
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
                    metadata={
                        "openverse": item,
                        "source_verified": verified,
                        "source_verification": {
                            "method": "schema.org/ImageObject",
                            "status": "verified" if verified else "review",
                        },
                    },
                    attribution=attribution,
                    exclusion_reason=",".join(reasons) or None,
                )
            )
            self.record_candidate(candidates[-1], verified=verified)

        return SearchResult(candidates, effective, next_offset)

    def download(self, candidate, target: Path):
        if candidate.exclusion_reason or not candidate.metadata.get("source_verified"):
            raise ValueError(candidate.exclusion_reason or "source_license_or_author_unverified")
        if license_class(self.policy, candidate.license) == "restricted":
            raise ValueError("restricted の候補は取得できません")
        self.get(candidate.original_url, target=target)
