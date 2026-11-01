from datetime import UTC, datetime
from urllib.error import HTTPError

import pytest

from colorstats.collect.commons import CommonsAdapter
from colorstats.collect.openverse import OpenverseAdapter
from colorstats.collect.policy import load_policy
from tests.test_collect import ROOT, Clock, Response


@pytest.fixture(params=[("wikimedia_commons", CommonsAdapter), ("openverse", OpenverseAdapter)])
def client(request):
    provider, adapter = request.param
    return provider, adapter


def make_client(client, responses, **changes):
    provider, adapter = client
    policy = {**load_policy(ROOT / "configs/source_policy.yaml", provider), **changes}
    clock, calls = Clock(), []
    responses = iter(responses)

    def opener(request, **kwargs):
        calls.append((request.full_url, clock.now))
        assert request.get_header("User-agent") == policy["user_agent"]
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    return adapter(policy, opener=opener, clock=clock.clock, wait=clock.wait), calls


@pytest.mark.parametrize("mode", ["json", "text", "file"])
@pytest.mark.parametrize("code", [429, 503])
def test_検索と元ページと原本が共通のRetryAfterで待機する(client, tmp_path, mode, code):
    error = HTTPError("https://example.test", code, "busy", {"Retry-After": "12"}, None)
    adapter, calls = make_client(client, [error, Response(b'{}'), Response(b'{}')])
    kwargs = {"json": {}, "text": {"text": True}, "file": {"target": tmp_path / "image"}}[mode]
    result = adapter.get("https://example.test/first", **kwargs)
    adapter.get("https://example.test/next")
    adapter.finish()
    assert [time for _, time in calls] == [0, 12, 13]
    assert adapter.clock() == 14
    if mode == "file":
        assert result is None and (tmp_path / "image").read_bytes() == b'{}'


@pytest.mark.parametrize("retries", [0, 1, 2])
def test_再試行回数と指数待機を両ソースで守る(client, retries):
    errors = [HTTPError("https://example.test", 429, "busy", {}, None)
              for _ in range(retries + 1)]
    adapter, calls = make_client(client, errors, retries=retries, backoff=3)
    with pytest.raises(RuntimeError, match="負荷制限"):
        adapter.get("https://example.test")
    assert [time for _, time in calls] == [0, 3, 9][:retries + 1]
    assert adapter.clock() == [3, 9, 21][retries]


@pytest.mark.parametrize("value,delay", [
    ("Sun, 01 Nov 2026 00:00:30 GMT", 30),
    ("Sat, 31 Oct 2026 00:00:00 GMT", 5),
    ("invalid", 5),
    ("1", 5),
])
def test_HTTP日時と不正なRetryAfterの扱いが共通である(client, monkeypatch, value, delay):
    class FixedDateTime:
        @staticmethod
        def now(tz):
            return datetime(2026, 11, 1, tzinfo=UTC)

    monkeypatch.setattr("colorstats.collect.http.datetime", FixedDateTime)
    adapter, calls = make_client(client, [
        HTTPError("https://example.test", 429, "busy", {"Retry-After": value}, None),
        Response({}),
    ])
    adapter.get("https://example.test")
    assert [time for _, time in calls] == [0, delay]


def test_再試行より取得間隔が長い場合も間隔を守る(client):
    adapter, calls = make_client(client, [
        HTTPError("https://example.test", 503, "busy", {}, None), Response({}),
    ], min_interval=10, backoff=1)
    adapter.get("https://example.test")
    assert [time for _, time in calls] == [0, 10]


def test_恒久エラーを再試行しない(client):
    adapter, calls = make_client(
        client, [HTTPError("https://example.test", 403, "denied", {}, None)]
    )
    with pytest.raises(HTTPError):
        adapter.get("https://example.test")
    adapter.finish()
    assert len(calls) == 1 and adapter.clock() == 1


def test_途中終了した原本を受理しない(client, tmp_path):
    adapter, _ = make_client(client, [Response(b"short", {"Content-Length": "100"})])
    with pytest.raises(OSError, match="途中"):
        adapter.get("https://example.test", target=tmp_path / "image")
