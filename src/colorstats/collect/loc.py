"""Library of CongressのJSON collection APIアダプター。"""

import io
import json
from pathlib import Path
from urllib.parse import urlencode

from PIL import Image

from colorstats.collect import Candidate, SearchRequest, SearchResult
from colorstats.collect.http import HttpClient, MeasurementLimit
from colorstats.collect.policy import license_class

COLLECTION = "john-margolies-roadside-america"
ENDPOINT = f"https://www.loc.gov/collections/{COLLECTION}/"


def _values(item, *keys):
    for key in keys:
        value = item.get(key)
        if isinstance(value, list):
            value = " | ".join(str(part) for part in value if part)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _is_color(data):
    with Image.open(io.BytesIO(data)) as image:
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("RGB")
        image.thumbnail((32, 32))
        return any(max(pixel) - min(pixel) > 2 for pixel in image.getdata())


def _read_json(response):
    data = response.read()
    content_type = response.headers.get("Content-Type", "").casefold()
    is_html = data.lstrip().lower().startswith((b"<!doctype html", b"<html"))
    if "text/html" in content_type or is_html:
        raise MeasurementLimit("LoCがHTMLまたはCAPTCHAを返したため、この測定を停止します")
    return json.loads(data)


def _read_image(response):
    data = response.read()
    content_type = response.headers.get("Content-Type", "").casefold()
    is_html = data.lstrip().lower().startswith((b"<!doctype html", b"<html"))
    if "text/html" in content_type or is_html:
        raise MeasurementLimit("LoCがHTMLまたはCAPTCHAを返したため、この測定を停止します")
    return data


class LoCAdapter(HttpClient):
    """文書化されたcollection JSONとAPI応答中の画像URLだけを利用する。"""

    def _get(self, url, *, api=False, read=None, target=None):
        try:
            return self.get(url, api=api, read=read or _read_json, target=target)
        except RuntimeError as error:
            if str(error) == "再試行後も取得を中断しました":
                raise MeasurementLimit("LoCが429/503を返したため、この測定を延期します") from error
            raise

    def search(self, request: SearchRequest) -> SearchResult:
        if request.provider != "loc":
            raise ValueError("LoC以外の検索リクエストです")
        start = request.start
        if start % request.limit:
            raise ValueError("LoCのページoffsetはlimitの倍数である必要があります")
        endpoint_type = self.policy.get("endpoint_type", "collection")
        if endpoint_type not in ("collection", "photos"):
            raise ValueError("LoC endpoint_typeはcollectionまたはphotosです")
        endpoint = ENDPOINT if endpoint_type == "collection" else "https://www.loc.gov/photos/"
        params = {
            "q": request.query,
            "fo": "json",
            "at": "results",
            "c": request.limit,
            "sp": start // request.limit + 1,
        }
        effective = {
            **params,
            "endpoint": endpoint,
            "api": "Library of Congress JSON API",
            "collection": COLLECTION if endpoint == ENDPOINT else None,
            "collection_bias": (
                "John Margoliesの米国沿道商業建築写真、1969-2008年に偏る"
                if endpoint == ENDPOINT else "LoC photos endpoint全般"
            ),
            "rank_basis": {"base": 0, "scope": "search", "calculation": "start + index"},
            "page_basis": {"base": 0, "value": request.page, "api_value": params["sp"]},
        }
        self.observe("search", {"effective": effective})
        response = self._get(endpoint + "?" + urlencode(params), api=True)
        hits = response.get("results", [])
        pagination = response.get("pagination", {})
        result_count = pagination.get("total", response.get("result_count", 0))
        end = start + len(hits)
        next_offset = end if pagination.get("next") or end < result_count else None
        self.observe("search", {"api_next_offset": next_offset, "api_results": hits})
        candidates = []
        for index, hit in enumerate(hits):
            rank = start + index
            source_url = hit.get("url") or hit.get("id") or ""
            image_urls = hit.get("image_url") or []
            if isinstance(image_urls, str):
                image_urls = [image_urls]
            image_url = next((url for url in image_urls if isinstance(url, str) and url), None)
            if image_url and image_url.startswith("//"):
                image_url = "https:" + image_url
            rights = _values(hit, "rights", "rights_advisory", "rights_and_access")
            title = hit.get("title") or ""
            license_name = "unknown"
            details = " ".join(
                str(hit.get(key, ""))
                for key in ("original_format", "format", "medium", "genre", "description")
            ).casefold()
            mime_values = _values(hit, "mime_type")
            mime = next(
                (part.strip() for part in (mime_values or "").split("|")
                 if part.strip().startswith("image/")),
                None,
            )
            reason = None
            if not source_url.startswith("https://www.loc.gov/"):
                reason = "invalid_source_url"
            elif hit.get("access_restricted") is True:
                reason = "access_restricted"
            elif not rights:
                reason = "rights_unavailable_review"
            elif "no known restrictions" in rights.casefold():
                license_name = "loc-analysis-only"
            elif "public domain" in rights.casefold():
                license_name = "pd"
            else:
                reason = "rights_unverified_review"
                license_name = "unknown"
            if any(term in (title + " " + details).casefold() for term in (
                "drawing", "map", "painting", "engraving", "lithograph", "blueprint",
            )):
                reason = "non_photo_or_drawing"
            if not image_url:
                reason = reason or "image_unavailable"
            if not mime:
                reason = reason or "non_image_or_mime_unavailable"
            self.observe("search", {"pending_candidate": {"source_url": source_url,
                                                               "original_url": image_url,
                                                               "rank": rank}})
            color = False
            if reason is None:
                try:
                    data = self._get(image_url, read=_read_image)
                    color = _is_color(data)
                except MeasurementLimit:
                    raise
                except Exception:
                    reason = "thumbnail_unavailable_or_invalid"
                if not color and reason is None:
                    reason = "monochrome_or_invalid_image"
            candidate = Candidate(
                source_url=source_url,
                original_url=image_url or "",
                rank=rank,
                page=request.page,
                title=title,
                author=_values(hit, "contributor", "contributors", "creator"),
                license=license_name,
                license_url=None,
                description=_values(hit, "description", "summary"),
                location=_values(hit, "location", "coordinates"),
                width=hit.get("width") or 0,
                height=hit.get("height") or 0,
                mime=mime or "unknown",
                metadata={"loc": hit, "rights_and_access": rights,
                          "rights_classification": license_name},
                attribution=" | ".join(filter(None, [
                    _values(hit, "contributor", "contributors", "creator"), source_url, rights,
                ])),
                exclusion_reason=reason,
                rendition={"provider": "loc", "native_id": hit.get("id") or source_url,
                           "revision": hit.get("timestamp"), "variant": "thumbnail"},
            )
            candidates.append(candidate)
            self.record_candidate(candidate, verified=reason is None)
        return SearchResult(candidates, effective, next_offset)

    def download(self, candidate: Candidate, target: Path) -> None:
        if candidate.exclusion_reason:
            raise ValueError(candidate.exclusion_reason)
        if license_class(self.policy, candidate.license) == "restricted":
            raise ValueError("restrictedの原本は取得できません")
        self._get(candidate.original_url, target=target)
