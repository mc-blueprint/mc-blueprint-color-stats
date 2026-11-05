import io
from datetime import UTC, datetime
from urllib.error import HTTPError

import pytest

from colorstats.collect.commons import CommonsAdapter
from colorstats.collect.http import HttpClient
from colorstats.collect.openverse import OpenverseAdapter
from colorstats.collect.policy import load_policy
from tests.test_collect import ROOT, Clock, Response


@pytest.fixture(params=[("wikimedia_commons", CommonsAdapter), ("openverse", OpenverseAdapter)])
def client(request):
    provider, adapter = request.param
    return provider, adapter


def make_client(client, responses, **changes):
    provider, adapter = client
    source_policy = load_policy(ROOT / "configs/source_policy.yaml", provider)
    policy = {
        **source_policy,
        "hosts": {
            **source_policy.get("hosts", {}),
            "example.test": {"kind": "page"},
        },
        **changes,
    }
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
    wait = 0.5 if client[0] == "wikimedia_commons" and mode == "file" else 1.0
    assert [time for _, time in calls] == [0, 12, 12 + wait]
    assert adapter.clock() == 12 + (3 if wait == 0.5 else 2) * wait
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


def test_Commons_APIの通常間隔と遅延応答後cooldownを分離する(client):
    policy = load_policy(ROOT / "configs/source_policy.yaml", "wikimedia_commons")
    clock, calls = Clock(), []

    class SlowResponse(Response):
        def read(self, *args):
            clock.wait(1.1)
            return super().read(*args)

    values = iter([SlowResponse(b"{}"), Response(b"{}"), Response(b"{}")])

    def opener(request, **kwargs):
        calls.append(clock.now)
        return next(values)

    http = HttpClient(policy, opener=opener, clock=clock.clock, wait=clock.wait)
    http.get("https://commons.wikimedia.org/w/api.php", api=True)
    http.get("https://commons.wikimedia.org/w/api.php", api=True)
    assert calls == [0, 6.1]
    http.get("https://commons.wikimedia.org/w/api.php", api=True)
    assert calls[-1] == 6.6


def test_未登録リダイレクト先へ通信しない(client):
    redirect = HTTPError(
        "https://example.test/first", 302, "redirect",
        {"Location": "https://unknown.test/file"}, io.BytesIO(),
    )
    adapter, calls = make_client(client, [redirect])
    with pytest.raises(ValueError, match="未登録"):
        adapter.get("https://example.test/first")
    assert len(calls) == 1


def test_Openverse匿名APIの時枠と日枠(client):
    policy = load_policy(ROOT / "configs/source_policy.yaml", "openverse")
    policy["api_windows"] = [{"seconds": 3600, "limit": 2}, {"seconds": 86400, "limit": 3}]
    clock, calls = Clock(), []

    def opener(request, **kwargs):
        calls.append(clock.now)
        return Response(b"{}")

    http = HttpClient(policy, opener=opener, clock=clock.clock, wait=clock.wait)
    for _ in range(4):
        http.get("https://api.openverse.org/v1/images/", api=True)
    assert calls == [0, 1, 3600, 86400]


def test_計測へ送るURLから秘密クエリを除く(client):
    adapter, _ = make_client(client, [Response(b"{}")])
    values = []
    adapter.observer = lambda event, value: values.append(value)
    adapter.observe("candidate", {"url": "https://example.test/image?token=secret&page=2"})
    assert values == [{"url": "https://example.test/image?page=2"}]


def test_Wikimedia_archive_pathを通信前に拒否する(tmp_path):
    adapter, calls = make_client(
        ("wikimedia_commons", CommonsAdapter), [Response(b"should not be requested")]
    )
    with pytest.raises(ValueError, match="禁止されたpath"):
        adapter.get(
            "https://upload.wikimedia.org/wikipedia/commons/archive/a/image.jpg",
            target=tmp_path / "image.jpg",
        )
    assert calls == []


def test_画像の10秒帯域枠をfixture応答で守る(client, tmp_path):
    adapter, _ = make_client(client, [Response(b"abcdefghijkl")],
                             media_bytes_per_10_seconds=8)
    target = tmp_path / "image"
    adapter.get("https://example.test/image", target=target)
    assert target.read_bytes() == b"abcdefghijkl"
    assert adapter.clock() == 10
