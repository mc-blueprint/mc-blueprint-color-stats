import io
from datetime import UTC, datetime
from urllib.error import HTTPError
from urllib.parse import urlsplit

import pytest

from colorstats.collect.commons import CommonsAdapter
from colorstats.collect.http import HttpClient, NonRetryableMeasurementLimit
from colorstats.collect.openverse import OpenverseAdapter
from colorstats.collect.policy import load_policy
from tests.test_collect import ROOT, Clock, Response


@pytest.fixture(params=[("wikimedia_commons", CommonsAdapter), ("openverse", OpenverseAdapter)])
def client(request):
    provider, adapter = request.param
    return provider, adapter


def make_client(client, responses, **changes):
    provider, adapter = client
    clock = changes.pop("clock", Clock())
    source_policy = load_policy(ROOT / "configs/source_policy.yaml", provider)
    policy = {
        **source_policy,
        "hosts": {
            **source_policy.get("hosts", {}),
            "example.test": {"kind": changes.pop("example_kind", "page")},
        },
        **changes,
    }
    calls = []
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
    wait = 1.0
    assert [time for _, time in calls] == [0, 12, 12 + wait]
    assert adapter.clock() == 12 + 2 * wait
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


def test_cloudflare_challengeは全adapterで即停止して再試行しない(client):
    error = HTTPError(
        "https://example.test", 403, "Forbidden", {"Cf-Mitigated": "challenge"}, None
    )
    adapter, calls = make_client(client, [error])
    with pytest.raises(NonRetryableMeasurementLimit, match="Cloudflare challenge"):
        adapter.get("https://example.test")
    assert len(calls) == 1


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
    policy["hosts"]["api.openverse.org"]["api_windows"] = [
        {"seconds": 3600, "limit": 2}, {"seconds": 86400, "limit": 3}
    ]
    clock, calls = Clock(), []

    def opener(request, **kwargs):
        calls.append(clock.now)
        return Response(b"{}")

    first = HttpClient(policy, opener=opener, clock=clock.clock, wait=clock.wait)
    second = HttpClient(policy, opener=opener, clock=clock.clock, wait=clock.wait)
    for _ in range(4):
        (first if _ < 2 else second).get("https://api.openverse.org/v1/images/")
    assert calls == [0, 1, 3600, 86400]


def test_別providerのclient間で同じmedia_hostの帯域窓を共有する(tmp_path):
    commons = load_policy(ROOT / "configs/source_policy.yaml", "wikimedia_commons")
    openverse = load_policy(ROOT / "configs/source_policy.yaml", "openverse")
    for policy in (commons, openverse):
        policy["hosts"]["upload.wikimedia.org"]["media_bytes_per_10_seconds"] = 4
    clock, calls = Clock(), []
    responses = iter((Response(b"abcd"), Response(b"efgh")))

    def opener(request, **kwargs):
        calls.append(clock.now)
        return next(responses)

    first = CommonsAdapter(commons, opener=opener, clock=clock.clock, wait=clock.wait)
    second = OpenverseAdapter(openverse, opener=opener, clock=clock.clock, wait=clock.wait)
    first.get("https://upload.wikimedia.org/first", target=tmp_path / "first")
    first.finish()
    second.get("https://upload.wikimedia.org/second", target=tmp_path / "second")
    assert calls == [0, 11]
    assert clock.now == 20


def test_redirect_host_policyがapi引数と元hostのkindに優先する():
    policy = load_policy(ROOT / "configs/source_policy.yaml", "openverse")
    policy["hosts"]["upload.wikimedia.org"]["min_interval"] = 1.0
    clock, calls, events = Clock(), [], []
    responses = iter((
        HTTPError(
            "https://upload.wikimedia.org/file", 302, "redirect",
            {"Location": "https://api.openverse.org/v1/images/"}, io.BytesIO(),
        ),
        Response(b"{}"),
    ))

    def opener(request, **kwargs):
        calls.append((request.full_url, clock.now))
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    adapter = OpenverseAdapter(policy, opener=opener, clock=clock.clock, wait=clock.wait)
    adapter.observer = lambda event, value: events.append(event)
    adapter.get(
        "https://upload.wikimedia.org/file", api=True, read=lambda response: response.read()
    )
    assert [event for event in events if event in ("request", "api_request")] == [
        "request", "api_request"
    ]
    assert calls == [
        ("https://upload.wikimedia.org/file", 0),
        ("https://api.openverse.org/v1/images/", 0),
    ]


@pytest.mark.parametrize("target", ["https://api.openverse.org/v1/", "https://example.test/next"])
def test_同hostと別hostへのredirectで秘密queryを送らない(target):
    policy = load_policy(ROOT / "configs/source_policy.yaml", "openverse")
    policy["hosts"]["example.test"] = {"kind": "page"}
    redirect = HTTPError(
        "https://example.test/start?access_token=private", 302, "redirect",
        {"Location": target + "?access_token=redirect-secret&client_secret=secret&page=2"},
        io.BytesIO(),
    )
    responses, urls = iter((redirect, Response(b"{}"))), []

    def opener(request, **kwargs):
        urls.append(request.full_url)
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    adapter = OpenverseAdapter(policy, opener=opener, clock=Clock().clock, wait=lambda _: None)
    adapter.get(
        "https://example.test/start?access_token=private", read=lambda response: response.read()
    )
    assert urls == [
        "https://example.test/start?access_token=private",
        target + "?page=2",
    ]


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
                             example_kind="media", media_bytes_per_10_seconds=8)
    target = tmp_path / "image"
    adapter.get("https://example.test/image", target=target)
    assert target.read_bytes() == b"abcdefghijkl"
    assert adapter.clock() == 10


def test_prepare再生成後も同一hostの40MB帯域枠を共有する(tmp_path):
    policy = load_policy(ROOT / "configs/source_policy.yaml", "wikimedia_commons")
    clock, calls = Clock(), []

    class TimedResponse(Response):
        def read(self, size=-1):
            data = super().read(size)
            clock.now += 2 * len(data) / 40_000_000
            return data

    responses = iter((TimedResponse(b"x" * 40_000_000), TimedResponse(b"y" * 40_000_000)))

    def opener(request, **kwargs):
        calls.append(clock.now)
        return next(responses)

    def prepare():
        return CommonsAdapter(policy, opener=opener, clock=clock.clock, wait=clock.wait)

    first = prepare()
    first.get("https://upload.wikimedia.org/first", target=tmp_path / "first")
    first.finish()
    second = prepare()
    second.get("https://upload.wikimedia.org/second", target=tmp_path / "second")

    assert calls[0] == 0 and calls[1] >= 10
    assert clock.now >= 20


def test_APIからmediaへのredirect後はtargetなしでも40MBを帯域制限する():
    policy = load_policy(ROOT / "configs/source_policy.yaml", "wikimedia_commons")
    clock, calls, waits = Clock(), [], []
    responses = iter((
        HTTPError(
            "https://commons.wikimedia.org/w/api.php", 302, "redirect",
            {"Location": "https://upload.wikimedia.org/file"}, io.BytesIO(),
        ),
        Response(b"x" * 40_000_000),
    ))

    def opener(request, **kwargs):
        calls.append((request.full_url, clock.now))
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    adapter = CommonsAdapter(policy, opener=opener, clock=clock.clock, wait=clock.wait)
    adapter.observer = lambda event, value: waits.append((event, value))
    body = adapter.get(
        "https://commons.wikimedia.org/w/api.php", read=lambda response: response.read()
    )

    assert len(body) == 40_000_000
    assert [urlsplit(url).hostname for url, _ in calls] == [
        "commons.wikimedia.org", "upload.wikimedia.org"
    ]
    assert clock.now >= 10
    assert any(event == "bandwidth_wait_seconds" for event, _ in waits)


def test_media_error本文3byteは一度だけ帯域枠へ計上する():
    policy = load_policy(ROOT / "configs/source_policy.yaml", "wikimedia_commons")
    clock, calls, waits = Clock(), [], []
    policy["hosts"]["example.test"] = {
        "kind": "media", "media_bytes_per_10_seconds": 7,
    }
    responses = iter((
        HTTPError("https://example.test/error", 500, "error", {}, io.BytesIO(b"abc")),
        Response(b"def"),
    ))

    def opener(request, **kwargs):
        calls.append(clock.now)
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    adapter = CommonsAdapter(policy, opener=opener, clock=clock.clock, wait=clock.wait)
    adapter.observer = lambda event, value: waits.append((event, value))
    with pytest.raises(HTTPError):
        adapter.get("https://example.test/error", read=lambda response: response.read())
    assert adapter.get("https://example.test/next", read=lambda response: response.read()) == b"def"

    assert calls == [0, 1.0]
    assert not any(event == "bandwidth_wait_seconds" for event, _ in waits)


def test_HTTP通信1秒とobserver4秒はnetwork時間に1秒だけ記録する():
    policy = load_policy(ROOT / "configs/source_policy.yaml", "wikimedia_commons")
    clock, observed = Clock(), []

    def opener(request, **kwargs):
        clock.now += 1
        raise HTTPError(request.full_url, 500, "error", {}, None)

    adapter = CommonsAdapter(policy, opener=opener, clock=clock.clock, wait=clock.wait)

    def observer(event, value):
        if event == "responses":
            clock.now += 4
        observed.append((event, value))

    adapter.observer = observer
    with pytest.raises(HTTPError):
        adapter.get("https://commons.wikimedia.org/w/api.php")

    assert clock.now == 5
    assert ("network_api_seconds", 1) in observed
