import json
from urllib.error import HTTPError
from urllib.parse import parse_qs

import pytest

from colorstats.collect import SearchRequest
from colorstats.collect.http import MeasurementLimit
from colorstats.collect.openverse import ENDPOINT, TOKEN_ENDPOINT, OpenverseAdapter
from colorstats.collect.policy import load_policy
from colorstats.collect.stage import enqueue_collect, prepare
from colorstats.queue.core import NonRetryableError
from tests.test_collect import Clock, Response, claim_for, payload_for
from tests.test_collect import isolated_acquisition_check as isolated_acquisition_check
from tests.test_openverse import FIXTURE, POLICY, source_page


@pytest.fixture
def standard(tmp_path, monkeypatch):
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    (tmp_path / "openverse-client-id").write_text("fixture-id")
    (tmp_path / "openverse-client-secret").write_text("fixture-secret")
    policy = load_policy(POLICY, "openverse")
    policy["auth_mode"] = "standard"
    return policy


def test_token取得と期限前更新と原host非転送(standard, tmp_path):
    item = json.loads(FIXTURE.read_text())["results"][0]
    clock, calls, events = Clock(), [], []

    def opener(request, **kwargs):
        calls.append(request)
        if request.full_url == TOKEN_ENDPOINT:
            assert request.get_method() == "POST"
            assert parse_qs(request.data.decode()) == {
                "grant_type": ["client_credentials"], "client_id": ["fixture-id"],
                "client_secret": ["fixture-secret"],
            }
            assert request.get_header("Authorization") is None
            return Response({"access_token": "fixture-token", "expires_in": 100})
        if request.full_url.startswith(ENDPOINT):
            assert request.get_header("Authorization") == "Bearer fixture-token"
            return Response({"results": [item]})
        assert request.get_header("Authorization") is None
        return Response(source_page(item).encode() if "flickr.com" in request.full_url
                        else b"image")

    adapter = OpenverseAdapter(standard, opener=opener, clock=clock.clock, wait=clock.wait)
    adapter.observer = lambda event, value: events.append((event, value))
    result = adapter.search(SearchRequest("openverse", "castle", limit=1))
    adapter.download(result.candidates[0], tmp_path / "image")
    adapter.get(ENDPOINT + "?q=castle")
    clock.now = 95
    adapter.get(ENDPOINT + "?q=castle")
    assert sum(r.full_url == TOKEN_ENDPOINT for r in calls) == 2
    assert adapter.policy["hosts"]["api.openverse.org"]["api_windows"] == [
        {"seconds": 60, "limit": 100}, {"seconds": 86400, "limit": 10000},
    ]
    serialized = json.dumps([events, result.parameters, standard])
    assert all(secret not in serialized for secret in
               ("fixture-id", "fixture-secret", "fixture-token"))


@pytest.mark.parametrize("code", [401, 403])
@pytest.mark.parametrize("endpoint", [TOKEN_ENDPOINT, ENDPOINT + "?q=test"])
def test_認証拒否後は匿名へ切り替えず停止(standard, code, endpoint):
    calls = []

    def opener(request, **kwargs):
        calls.append(request.full_url)
        if request.full_url == endpoint:
            raise HTTPError(request.full_url, code, "fixture-secret", {}, None)
        return Response({"access_token": "fixture-token", "expires_in": 100})

    adapter = OpenverseAdapter(standard, opener=opener, wait=lambda _: None)
    with pytest.raises(NonRetryableError) as error:
        adapter.get(ENDPOINT + "?q=test")
    assert "fixture" not in str(error.value)
    count = len(calls)
    with pytest.raises(NonRetryableError):
        adapter.get(ENDPOINT + "?q=test")
    assert len(calls) == count


def test_credential欠落は通信前停止し匿名は読まない(standard, tmp_path):
    (tmp_path / "openverse-client-secret").unlink()
    calls = []
    adapter = OpenverseAdapter(standard, opener=lambda *a, **k: calls.append(a))
    with pytest.raises(NonRetryableError):
        adapter.get(ENDPOINT + "?q=test")
    assert not calls
    standard["auth_mode"] = "anonymous"
    adapter = OpenverseAdapter(standard, opener=lambda *a, **k: Response({}), wait=lambda _: None)
    adapter.get(ENDPOINT + "?q=test")
    assert adapter._token is None


@pytest.mark.parametrize("token_redirect", [True, False])
def test_redirectへ認証とPOSTを転送しない(standard, token_redirect):
    calls = []
    standard["hosts"]["example.test"] = {"kind": "page"}

    def opener(request, **kwargs):
        calls.append(request)
        if request.full_url == TOKEN_ENDPOINT and not token_redirect:
            return Response({"access_token": "fixture-token", "expires_in": 100})
        if request.full_url.startswith("https://api.openverse.org/"):
            raise HTTPError(request.full_url, 302, "redirect", {
                "Location": "https://example.test/page?access_token=fixture-token",
            }, None)
        pytest.fail("登録APIのredirect先へ通信してはいけません")

    adapter = OpenverseAdapter(standard, opener=opener, wait=lambda _: None)
    with pytest.raises(NonRetryableError):
        adapter.get(ENDPOINT + "?q=test")
    assert len(calls) == (1 if token_redirect else 2)


@pytest.mark.parametrize("endpoint", [TOKEN_ENDPOINT, ENDPOINT + "?q=test"])
def test_429の日単位RetryAfterを短周期反復しない(standard, endpoint):
    clock, times = Clock(), []
    busy = [True]

    def opener(request, **kwargs):
        if request.full_url == endpoint:
            times.append(clock.now)
            if busy.pop() if busy else False:
                raise HTTPError(endpoint, 429, "busy", {"Retry-After": "86400"}, None)
        return Response({"access_token": "fixture-token", "expires_in": 200000})

    adapter = OpenverseAdapter(standard, opener=opener, clock=clock.clock, wait=clock.wait)
    adapter.get(ENDPOINT + "?q=test")
    assert len(times) == 2 and times[1] - times[0] >= 86400


def test_DB枠待機中に失効したtokenも送信前に更新する(standard):
    clock, tokens, sent = Clock(), [], []

    def opener(request, **kwargs):
        if request.full_url == TOKEN_ENDPOINT:
            tokens.append(clock.now)
            return Response({"access_token": "fixture-token", "expires_in": 100})
        sent.append(clock.now)
        assert sent[-1] < tokens[-1] + 90
        return Response({})

    adapter = OpenverseAdapter(standard, opener=opener, clock=clock.clock, wait=clock.wait)
    adapter.get(ENDPOINT + "?q=test")
    delays = iter([86400, 0, 0])
    adapter.quota_reserve = lambda *args: next(delays, 0)
    adapter.get(ENDPOINT + "?q=test")
    assert len(tokens) == 2 and sent[-1] >= 86400


@pytest.mark.parametrize("location", [ENDPOINT + "?q=redirect", TOKEN_ENDPOINT])
def test_登録APIの同host_redirectは匿名要求を送らず停止する(standard, location):
    calls = []

    def opener(request, **kwargs):
        calls.append(request)
        if len(calls) == 1:
            return Response({"access_token": "fixture-token", "expires_in": 100})
        if len(calls) == 2:
            raise HTTPError(request.full_url, 302, "redirect", {"Location": location}, None)
        pytest.fail("登録APIのredirect先へ匿名要求を送ってはいけません")

    with pytest.raises(NonRetryableError):
        OpenverseAdapter(standard, opener=opener, wait=lambda _: None).get(ENDPOINT + "?q=test")
    assert len(calls) == 2


@pytest.mark.parametrize("host", ["api.openverse.org", "api.openverse.org.",
                                  "API.OPENVERSE.ORG", "API.OPENVERSE.ORG."])
@pytest.mark.parametrize("path", ["/v1/images/", "/v1/auth_tokens/token/"])
def test_元ページから登録APIへのredirectはhost表記によらず通信前に拒否する(
    standard, host, path
):
    calls = []
    url = "https://www.flickr.com/page"

    def opener(request, **kwargs):
        calls.append(request.full_url)
        if request.full_url == url:
            raise HTTPError(url, 302, "redirect", {"Location": f"https://{host}{path}"}, None)
        pytest.fail("元ページのredirectから登録APIへ匿名要求を送ってはいけません")

    adapter = OpenverseAdapter(standard, opener=opener, wait=lambda _: None)
    adapter._token, adapter._expires = "fixture-token", float("inf")
    with pytest.raises(NonRetryableError, match="登録APIへのredirect"):
        adapter.get(url)
    assert calls == [url]


@pytest.mark.parametrize("data", [
    {}, {"access_token": "fixture-token", "expires_in": 0},
    {"access_token": "fixture-token", "expires_in": "nan"},
    {"access_token": "fixture-token", "expires_in": 100, "token_type": "Basic"},
])
def test_不正token応答では検索せず秘密を例外に含めない(standard, data):
    calls = []

    def opener(request, **kwargs):
        calls.append(request.full_url)
        return Response(data)

    with pytest.raises(NonRetryableError) as error:
        OpenverseAdapter(standard, opener=opener).get(ENDPOINT + "?q=test")
    assert calls == [TOKEN_ENDPOINT] and "fixture-token" not in str(error.value)


def test_standardは共有台帳なしの通常収集を通信前に止める(standard, tmp_path):
    payload, config_hash = payload_for(tmp_path)
    payload["request"]["provider"] = "openverse"
    payload["policy"] = standard
    with pytest.raises(NonRetryableError, match="共有枠台帳"):
        prepare(claim_for(payload, config_hash))


def test_認証modeはjobを分離しcredential値をpayloadとhashへ入れない(
    standard, tmp_path
):
    import yaml

    storage = tmp_path / "storage.yaml"
    storage.write_text("storage: {raw: []}\n")
    policy_path = tmp_path / "policy.yaml"
    jobs = []

    class Queue:
        def enqueue(self, stage, asset_id, config_hash, payload):
            jobs.append((config_hash, payload))

    def enqueue():
        enqueue_collect(Queue(), SearchRequest("openverse", "castle"), policy_path=policy_path,
                        storage_config=storage, host="ubuntu-1", domain="real_building",
                        code_version="fixture", taxonomy_version="0.1.0")

    for mode in ("anonymous", "standard"):
        standard["auth_mode"] = mode
        policy_path.write_text(yaml.safe_dump({"sources": {"openverse": standard}}))
        enqueue()
    assert jobs[0][0] != jobs[1][0]
    for name in ("openverse-client-id", "openverse-client-secret"):
        (tmp_path / name).write_text("fixture-rotated")
    enqueue()
    assert jobs[1] == jobs[2]
    assert all(secret not in json.dumps(jobs) for secret in
               ("fixture-id", "fixture-secret", "fixture-rotated"))


def test_queryなしでも登録認証で検索する(standard):
    calls = []

    def opener(request, **kwargs):
        calls.append(request)
        if request.full_url == TOKEN_ENDPOINT:
            return Response({"access_token": "fixture-token", "expires_in": 100})
        assert request.get_header("Authorization") == "Bearer fixture-token"
        return Response({})

    OpenverseAdapter(standard, opener=opener, wait=lambda _: None).get(ENDPOINT)
    assert len(calls) == 2


@pytest.mark.parametrize("url", ["http://api.openverse.org/v1/images/",
                                 "https://api.openverse.org/v1/other/"])
def test_標準モードから匿名API経路を使わない(standard, url):
    calls = []
    with pytest.raises(NonRetryableError):
        OpenverseAdapter(standard, opener=lambda *a, **k: calls.append(a)).get(url)
    assert not calls


def test_token取得も測定予算の正常停止を維持する(standard):
    def exhausted(*args, **kwargs):
        raise MeasurementLimit("provider_api_limit")

    with pytest.raises(MeasurementLimit, match="provider_api_limit"):
        OpenverseAdapter(standard, opener=exhausted).get(ENDPOINT)


def test_待機で失効する短命tokenを送信しない(standard):
    clock, calls = Clock(), []

    def opener(request, **kwargs):
        calls.append(request.full_url)
        return Response({"access_token": "fixture-token", "expires_in": 1})

    with pytest.raises(NonRetryableError, match="有効時間"):
        OpenverseAdapter(standard, opener=opener, clock=clock.clock,
                         wait=clock.wait).get(ENDPOINT)
    assert calls == [TOKEN_ENDPOINT]
