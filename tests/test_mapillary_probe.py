import runpy

import pytest
import yaml

from colorstats.collect.http import HttpClient
from tests.test_collect import ROOT, Clock, Response
from tests.test_mapillary import setup  # noqa: F401
from tests.test_mapillary_stop import disable


def test_probeはcwdの許可で現行policy無効化を迂回しない(
    setup, tmp_path, monkeypatch,  # noqa: F811
):
    config = tmp_path / "configs"
    config.mkdir()
    (config / "source_policy.yaml").write_text(yaml.safe_dump({"sources": {"mapillary": setup}}))
    monkeypatch.chdir(tmp_path)
    disable()
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(args)
        raise AssertionError("通信前に停止しなければなりません")

    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    monkeypatch.setattr("colorstats.collect.http.build_opener", forbidden)
    probe = runpy.run_path(str(ROOT / "bench/issue94/probe.py"))
    with pytest.raises(ValueError, match="source_policy"):
        probe["main"](tmp_path)
    assert not calls and not (tmp_path / "budget.json").exists()


def test_probeのrobots取得も共通HTTPと現行policyを使う(
    setup, tmp_path, monkeypatch,  # noqa: F811
):
    monkeypatch.chdir(tmp_path)
    calls = []
    clock = Clock()

    def opener(request, **kwargs):
        calls.append(request)
        return Response(b"User-agent: *\nDisallow: /\n")

    probe = runpy.run_path(str(ROOT / "bench/issue94/probe.py"))
    monkeypatch.setitem(probe["main"].__globals__, "HttpClient", lambda policy: HttpClient(
        policy, opener=opener, clock=clock.clock, wait=clock.wait))
    with pytest.raises(SystemExit, match="robotsの許可"):
        probe["main"](tmp_path)
    assert len(calls) == 1
    assert calls[0].full_url == "https://graph.mapillary.com/robots.txt"
    assert calls[0].get_header("User-agent") == setup["user_agent"]
    assert calls[0].get_header("Authorization") is None
    assert clock.now >= setup["min_interval"]
