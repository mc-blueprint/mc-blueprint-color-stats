import json
from dataclasses import asdict, replace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from colorstats.collect import SearchRequest
from colorstats.collect.mapillary import ENDPOINT, MapillaryAdapter
from colorstats.collect.policy import load_policy
from colorstats.queue.core import NonRetryableError
from tests.test_collect import ROOT, Clock, Response


@pytest.fixture
def setup(tmp_path, monkeypatch):
    credentials = tmp_path / "credentials"
    credentials.mkdir()
    (credentials / "mapillary-client-token").write_text("MLY|test-secret")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credentials))
    monkeypatch.setenv("STATE_DIRECTORY", str(tmp_path / "state"))
    sources = yaml.safe_load((ROOT / "configs/source_policy.yaml").read_text())["sources"]
    policy = sources["mapillary"]
    policy = {**policy, "enabled": True}
    current = tmp_path / "source_policy.yaml"
    current.write_text(yaml.safe_dump({"sources": {"mapillary": policy}}))
    monkeypatch.setenv("COLORSTATS_SOURCE_POLICY", str(current))
    return policy


def item(**changes):
    fixture = json.loads((ROOT / "tests/fixtures/mapillary.json").read_text())
    return {**fixture["data"][0], **changes}


def client(policy, responses):
    clock = Clock()
    calls = []
    responses = iter(responses)

    def opener(request, **kwargs):
        calls.append(request)
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return Response(response)

    return MapillaryAdapter(policy, opener=opener, clock=clock.clock, wait=clock.wait), calls


def request(**changes):
    return SearchRequest("mapillary", "kyoto-street-buildings", **changes)


def test_固定検索と継続を別インスタンスから再開し連写を除外する(setup):
    adapter, calls = client(setup, [{"data": [item()], "paging": {
        "next": ENDPOINT + "?access_token=secret", "cursors": {"after": "cursor-1"}}}])
    first = adapter.search(request(limit=1))
    assert first.next_offset == 1
    assert first.candidates[0].rank == 0
    adapter, calls = client(setup, [{"data": [item(id="124")]}])
    second = adapter.search(request(limit=1, offset=1, page=1))
    assert second.next_offset is None
    assert second.candidates[0].rank == 1
    assert second.candidates[0].exclusion_reason == "sequence_repeat"
    assert parse_qs(urlsplit(calls[0].full_url).query)["after"] == ["cursor-1"]
    with pytest.raises(ValueError, match="未確認offset"):
        adapter.search(request(limit=1, offset=99))


def test_認証と署名を候補や観測値へ保存せずCDNへ転送しない(setup, tmp_path):
    adapter, calls = client(setup, [{"data": [item()]}, b"image"])
    events = []
    adapter.observer = lambda *args: events.append(args)
    result = adapter.search(request())
    candidate = result.candidates[0]
    adapter.download(candidate, tmp_path / "image")
    assert calls[0].get_header("Authorization") == "OAuth MLY|test-secret"
    assert calls[1].get_header("Authorization") is None
    assert "secret" not in json.dumps([asdict(candidate), result.parameters, events])
    assert "signature" not in json.dumps([asdict(candidate), result.parameters, events])
    assert "MLY|" not in json.dumps(setup)


@pytest.mark.parametrize("changes,reason", [
    ({"detections": {}}, "privacy_unverified"),
    ({"detections": {"data": [], "paging": {"next": "x"}}}, "privacy_unverified"),
    ({"detections": {"data": [{"value": "human--person"}]}}, "person_present"),
    ({"creator": {}}, "identity_unverified"),
    ({"width": 0}, "non_image"),
    ({"thumb_1024_url": "https://evil.test/a.jpg"}, "thumbnail_unverified"),
])
def test_未確認と人物と非画像を画像取得前に除外する(setup, changes, reason, tmp_path):
    adapter, calls = client(setup, [{"data": [item(**changes)]}])
    candidate = adapter.search(request()).candidates[0]
    assert reason in candidate.exclusion_reason
    with pytest.raises(ValueError):
        adapter.download(candidate, tmp_path / "image")
    assert len(calls) == 1


def test_未対応語と認証欠落は通信しない(setup, monkeypatch):
    adapter, calls = client(setup, [])
    with pytest.raises(ValueError, match="固定検索"):
        adapter.search(replace(request(), query="anything"))
    monkeypatch.delenv("CREDENTIALS_DIRECTORY")
    with pytest.raises(ValueError, match="ソースは無効"):
        adapter.search(request())
    assert not calls


def test_credentialファイル欠落でも別認証へ切り替えない(setup, monkeypatch, tmp_path):
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path / "missing"))
    monkeypatch.setenv("MAPILLARY_ACCESS_TOKEN", "MLY|unused")
    adapter, calls = client(setup, [])
    with pytest.raises(ValueError, match="ソースは無効"):
        adapter.search(request())
    assert not calls


@pytest.mark.parametrize("code", [400, 401, 403, 404, 429])
def test_API失敗は秘密を含めず停止し別経路へ移らない(setup, code):
    adapter, calls = client(setup, [HTTPError(
        ENDPOINT + "?access_token=secret", code, "secret", {"Retry-After": "90"}, None)])
    with pytest.raises((HTTPError, RuntimeError)) as error:
        adapter.search(request())
    assert "secret" not in str(error.value)
    assert len(calls) == 1
    if code == 429:
        assert adapter.clock() >= 90


def test_リダイレクト先への認証非転送と公開外経路の拒否(setup):
    adapter, calls = client(setup, [HTTPError(ENDPOINT, 302, "", {
        "Location": "https://scontent.example.fbcdn.net/image?access_token=secret"}, None), {}])
    adapter.get(ENDPOINT)
    assert calls[1].get_header("Authorization") is None
    assert "access_token" not in calls[1].full_url
    with pytest.raises(ValueError, match="公開Images API"):
        adapter.get("https://graph.mapillary.com/graphql/")


def test_署名URL失効は再取得で更新しnativeIDは維持する(setup, tmp_path):
    adapter, calls = client(setup, [{"data": [item()]}, HTTPError(
        "https://scontent.example.fbcdn.net/image?access_token=secret", 403, "secret", {}, None)])
    candidate = adapter.search(request()).candidates[0]
    with pytest.raises(NonRetryableError) as error:
        adapter.download(candidate, tmp_path / "image")
    assert "secret" not in str(error.value)
    adapter, _ = client(setup, [{"data": [item(
        thumb_1024_url="https://scontent.example.fbcdn.net/new.jpg?access_token=new")]}, b"new"])
    refreshed = adapter.search(request()).candidates[0]
    assert refreshed.original_url == candidate.original_url
    adapter.download(refreshed, tmp_path / "new")


def test_同一ページ内の連写と失効した権利を画像取得前に除外する(setup):
    adapter, _ = client(setup, [{"data": [item(), item(id="124")]}])
    candidates = adapter.search(request()).candidates
    assert candidates[0].exclusion_reason is None
    assert candidates[1].exclusion_reason == "sequence_repeat"
    adapter.policy["rights_review"]["revoked"] = True
    with pytest.raises(ValueError, match="根拠"):
        adapter.search(request())


def test_実運用ポリシーはrobots判断まで無効である():
    with pytest.raises(ValueError, match="source_policy"):
        load_policy(ROOT / "configs/source_policy.yaml", "mapillary")


def test_収集目標は明示意図だけを使い無作為offsetを生成しない():
    import random

    from colorstats.collect.targets import requests

    config = {"search": {"providers": ["mapillary"], "limit": 2}}
    layer = {"id": "kyoto", "mapillary_searches": ["kyoto-street-buildings"]}
    result = list(requests(config, layer, random.Random(0)))
    assert len(result) == 1 and result[0].start == 0
    assert result[0].query == "kyoto-street-buildings"
    with pytest.raises(ValueError, match="mapillary_searches"):
        list(requests(config, {"id": "unknown"}, random.Random(0)))
