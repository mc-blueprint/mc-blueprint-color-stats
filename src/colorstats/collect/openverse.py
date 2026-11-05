"""Openverse API を使う画像検索アダプター。"""

import json
import os
from copy import deepcopy
from html.parser import HTMLParser
from math import isfinite
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit

from colorstats.collect import Candidate, SearchResult
from colorstats.collect.http import HttpClient, MeasurementLimit
from colorstats.collect.policy import license_class
from colorstats.queue.core import NonRetryableError

ENDPOINT = "https://api.openverse.org/v1/images/"
TOKEN_ENDPOINT = "https://api.openverse.org/v1/auth_tokens/token/"
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
    """policyのanonymous/standardで検索し、元ページを完全照合する。

    standardはsystemd credential必須。tokenはメモリ内のみで期限前に再取得し、
    認証失敗時は停止する。元ページ・原画像・redirectに認証を渡さない。
    """

    def __init__(self, policy, **kwargs):
        policy = deepcopy(policy)
        self.auth_mode = policy.get("auth_mode", "anonymous")
        if self.auth_mode not in ("anonymous", "standard"):
            raise ValueError("Openverse auth_modeはanonymousまたはstandardです")
        if self.auth_mode == "standard":
            policy["hosts"]["api.openverse.org"]["api_windows"] = policy[
                "standard_api_windows"
            ]
        super().__init__(policy, **kwargs)
        self._token = None
        self._expires = 0
        self._auth_failed = False
        opener = self.opener

        def authorized(request, **options):
            parts = urlsplit(request.full_url)
            if (parts.hostname or "").lower().rstrip(".") == "api.openverse.org":
                if self.auth_mode == "standard" and request.colorstats_redirected:
                    raise NonRetryableError("Openverse登録APIへのredirectを拒否しました")
                if parts.scheme != "https" or parts.port not in (None, 443):
                    raise NonRetryableError("Openverse APIはHTTPSの標準ポートだけを使用します")
                if (self.auth_mode == "standard" and not request.colorstats_redirected
                        and parts.path not in ("/v1/images/", "/v1/auth_tokens/token/")):
                    raise NonRetryableError("Openverseの未対応endpointへの要求を拒否しました")
            if (self.auth_mode == "standard" and request.full_url == TOKEN_ENDPOINT
                    and not request.colorstats_redirected):
                directory = os.environ.get("CREDENTIALS_DIRECTORY")
                try:
                    if not directory:
                        raise OSError
                    client_id = (Path(directory) / "openverse-client-id").read_text().strip()
                    secret = (Path(directory) / "openverse-client-secret").read_text().strip()
                    if not client_id or not secret:
                        raise OSError
                except OSError:
                    raise NonRetryableError("Openverse credentialがないため停止します") from None
                request.data = urlencode({"grant_type": "client_credentials",
                                          "client_id": client_id,
                                          "client_secret": secret}).encode()
                request.add_header("Content-Type", "application/x-www-form-urlencoded")
            elif (self.auth_mode == "standard"
                  and (request.full_url == ENDPOINT or request.full_url.startswith(ENDPOINT + "?"))
                  and not request.colorstats_redirected):
                request.add_header("Authorization", "Bearer " + self._token)
            return opener(request, **options)

        self.opener = authorized

    def _wait_for_slot(self, url):
        if self._auth_failed:
            raise NonRetryableError("Openverse認証失敗後の通信を停止します")
        slot = super()._wait_for_slot(url)
        if self.auth_mode == "standard" and (url == ENDPOINT or url.startswith(ENDPOINT + "?")):
            if not self._token or self.clock() >= self._expires:
                try:
                    data = super().get(TOKEN_ENDPOINT, follow_redirects=False)
                    token, lifetime = data["access_token"], float(data["expires_in"])
                    if (not isinstance(token, str) or not token or not isfinite(lifetime)
                            or lifetime <= 0
                            or any(c.isspace() for c in token)
                            or data.get("token_type", "Bearer").casefold() != "bearer"):
                        raise ValueError
                except MeasurementLimit:
                    raise
                except Exception:
                    self._auth_failed = True
                    self._token = None
                    raise NonRetryableError("Openverse token取得に失敗したため停止します") from None
                self._token = token
                self._expires = self.clock() + lifetime * 0.9
                slot = super()._wait_for_slot(url)
                if self.clock() >= self._expires:
                    self._token = None
                    raise NonRetryableError(
                        "Openverse tokenの有効時間が取得間隔より短いため停止します"
                    )
        return slot

    def get(self, url, **kwargs):
        if self.auth_mode == "standard" and (url == ENDPOINT or url.startswith(ENDPOINT + "?")):
            kwargs["follow_redirects"] = False
        try:
            return super().get(url, **kwargs)
        except HTTPError as error:
            code = error.code
            error.close()
            if url.startswith(ENDPOINT) and code in (401, 403):
                self._auth_failed = True
                self._token = None
                raise NonRetryableError(f"Openverse認証・アクセス拒否: HTTP {code}") from None
            raise HTTPError(self._without_secret_query(url), code,
                            "Openverse HTTP error", {}, None) from None

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
        effective["authentication"] = {
            "mode": self.auth_mode, "tier": self.auth_mode,
            "api_windows": self.policy["hosts"]["api.openverse.org"]["api_windows"],
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
