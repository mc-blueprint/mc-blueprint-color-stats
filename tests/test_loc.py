import io
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml
from PIL import Image

from colorstats.collect import SearchRequest
from colorstats.collect.http import MeasurementLimit
from colorstats.collect.loc import COLLECTION, LoCAdapter
from colorstats.collect.policy import load_policy

ROOT = Path(__file__).resolve().parents[1]


def policy_for_test():
    sources = yaml.safe_load(
        (ROOT / "configs/source_policy.yaml").read_text(encoding="utf-8")
    )["sources"]
    policy = sources["loc"]
    policy["enabled"] = True
    return policy


@pytest.fixture(autouse=True)
def current_loc_policy(tmp_path, monkeypatch):
    sources = yaml.safe_load((ROOT / "configs/source_policy.yaml").read_text(encoding="utf-8"))
    sources["sources"]["loc"]["enabled"] = True
    path = tmp_path / "source_policy.yaml"
    path.write_text(yaml.safe_dump(sources), encoding="utf-8")
    monkeypatch.setenv("COLORSTATS_SOURCE_POLICY", str(path))


class Response(io.BytesIO):
    def __init__(self, value):
        if isinstance(value, dict):
            value = json.dumps(value).encode()
        super().__init__(value)
        self.headers = {}


class Clock:
    now = 0

    def wait(self, seconds):
        self.now += seconds


def jpeg(color):
    output = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(output, format="JPEG")
    return output.getvalue()


def adapter_for(responses, *, endpoint_type="collection"):
    policy = policy_for_test()
    policy["endpoint_type"] = endpoint_type
    clock = Clock()
    requests = []

    def opener(request, **kwargs):
        requests.append((request, clock.now))
        return responses.pop(0)

    return LoCAdapter(policy, opener=opener, clock=lambda: clock.now, wait=clock.wait), requests


def hit(**updates):
    value = {
        "id": "https://www.loc.gov/item/2020123456/",
        "url": "https://www.loc.gov/item/2020123456/",
        "title": "Color roadside photograph",
        "contributor": ["Photographer"],
        "rights_advisory": ["No known restrictions."],
        "image_url": ["https://tile.loc.gov/service/pnp/example_150px.jpg"],
        "mime_type": ["image/jpeg"],
    }
    value.update(updates)
    return value


def test_collection検索のページ権利記述とカラー判定():
    payload = {
        "pagination": {"total": 15},
        "results": [hit()],
    }
    adapter, requests = adapter_for([Response(payload), Response(jpeg((210, 40, 20)))])
    request = SearchRequest("loc", "roadside architecture", page=1, offset=10, limit=1)
    result = adapter.search(request)
    candidate = result.candidates[0]
    assert result.next_offset == 11
    assert candidate.rank == 10 and candidate.page == 1
    assert candidate.license == "loc-analysis-only"
    assert candidate.metadata["rights_and_access"] == "No known restrictions."
    assert candidate.exclusion_reason is None
    assert candidate.rendition["native_id"] == hit()["id"]
    assert "米国沿道商業建築" in result.parameters["collection_bias"]
    assert requests[0][0].full_url.startswith(
        f"https://www.loc.gov/collections/{COLLECTION}/?"
    )
    assert parse_qs(urlsplit(requests[0][0].full_url).query) == {
        "q": ["roadside architecture"], "fo": ["json"], "at": ["results"],
        "c": ["1"], "sp": ["11"],
    }
    assert requests[1][0].full_url == hit()["image_url"][0]
    assert requests[1][1] - requests[0][1] >= 6


def test_photos経路と権利不明候補の画像取得前除外():
    payload = {"pagination": {"total": 1}, "results": [hit(rights_advisory=[])]}
    adapter, requests = adapter_for([Response(payload)], endpoint_type="photos")
    result = adapter.search(SearchRequest("loc", "building", limit=1))
    assert requests[0][0].full_url.startswith("https://www.loc.gov/photos/?")
    assert result.candidates[0].exclusion_reason == "rights_unavailable_review"
    assert len(requests) == 1

    payload = {"pagination": {"total": 1}, "results": [hit(rights=["CC BY 4.0"])]}
    adapter, requests = adapter_for([Response(payload)])
    result = adapter.search(SearchRequest("loc", "building", limit=1))
    assert result.candidates[0].license == "unknown"
    assert result.candidates[0].exclusion_reason == "rights_unverified_review"
    assert len(requests) == 1


def test明記されたpublic_domainだけをopenにし権利不明は取得しない(tmp_path):
    payload = {"pagination": {"total": 1}, "results": [hit(rights=["Public domain."])]}
    adapter, _ = adapter_for([Response(payload), Response(jpeg((20, 180, 50)))])
    candidate = adapter.search(SearchRequest("loc", "building", limit=1)).candidates[0]
    assert candidate.license == "pd"
    assert candidate.exclusion_reason is None

    restricted = candidate.__class__(**{
        **candidate.__dict__, "license": "unknown", "exclusion_reason": "rights_unverified_review",
    })
    try:
        adapter.download(restricted, tmp_path / "blocked.jpg")
    except ValueError as error:
        assert str(error) == "rights_unverified_review"
    else:
        raise AssertionError("権利不明候補の取得を許してしまった")


def test図面とモノクロ画像は原本取得前に除外する():
    payload = {"pagination": {"total": 2}, "results": [
        hit(title="Architectural drawing"), hit(id="https://www.loc.gov/item/2/"),
    ]}
    adapter, requests = adapter_for([
        Response(payload), Response(jpeg((120, 120, 120))),
    ])
    result = adapter.search(SearchRequest("loc", "architecture", limit=2))
    assert result.candidates[0].exclusion_reason == "non_photo_or_drawing"
    assert result.candidates[1].exclusion_reason == "monochrome_or_invalid_image"
    assert len(requests) == 2


def test_captchaとrate_limitで測定を停止する():
    adapter, _ = adapter_for([Response(b"<html>CAPTCHA</html>")])
    with pytest.raises(MeasurementLimit, match="HTMLまたはCAPTCHA"):
        adapter.search(SearchRequest("loc", "building", limit=1))

    policy = policy_for_test()
    clock = Clock()

    def rate_limited(request, **kwargs):
        raise HTTPError(request.full_url, 429, "too many requests", {"Retry-After": "5"}, None)

    adapter = LoCAdapter(policy, opener=rate_limited, clock=lambda: clock.now, wait=clock.wait)
    with pytest.raises(MeasurementLimit, match="429/503"):
        adapter.search(SearchRequest("loc", "building", limit=1))


def test_cloudflare_challengeは即停止し再試行しない():
    policy = policy_for_test()
    calls = []

    def challenged(request, **kwargs):
        calls.append(request.full_url)
        raise HTTPError(request.full_url, 403, "Forbidden", {"Cf-Mitigated": "challenge"}, None)

    adapter = LoCAdapter(policy, opener=challenged)
    with pytest.raises(MeasurementLimit, match="Cloudflare challenge"):
        adapter.search(SearchRequest("loc", "building", limit=1))
    assert len(calls) == 1


def test_source_policyでLoC取得を無効化している():
    with pytest.raises(ValueError, match="source_policy"):
        load_policy(ROOT / "configs/source_policy.yaml", "loc")
