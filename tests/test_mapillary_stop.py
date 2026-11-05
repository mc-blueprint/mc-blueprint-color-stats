import json
import os
from dataclasses import asdict
from pathlib import Path
from urllib.error import HTTPError

import pytest
import yaml

from colorstats.collect import SearchRequest, stage
from colorstats.collect.http import HttpClient
from colorstats.collect.openverse import ENDPOINT, OpenverseAdapter
from colorstats.collect.policy import load_policy
from colorstats.queue.core import NonRetryableError
from colorstats.queue.worker import Worker
from colorstats.schema.models import Job
from tests.test_collect import ROOT, Clock, Response, claim_for, payload_for
from tests.test_mapillary import setup  # noqa: F401
from tests.test_openverse import FIXTURE
from tests.test_queue import database, queue  # noqa: F401


def disable():
    current = Path(os.environ["COLORSTATS_SOURCE_POLICY"])
    sources = yaml.safe_load(current.read_text())
    sources["sources"]["mapillary"]["enabled"] = False
    current.write_text(yaml.safe_dump(sources))


@pytest.mark.parametrize("host", ["graph.mapillary.com", "www.mapillary.com",
                                 "images.mapillary.com", "scontent.example.fbcdn.net"])
def test_現行無効化は全hostを保存済み許可より優先する(setup, host):  # noqa: F811
    policy = load_policy(ROOT / "configs/source_policy.yaml", "openverse")
    policy["hosts"]["fbcdn.net"] = {"kind": "media"}
    policy["hosts"]["graph.mapillary.com"] = {"kind": "api"}
    calls = []
    adapter = HttpClient(policy, opener=lambda *args, **kwargs: calls.append(args))
    disable()
    with pytest.raises(NonRetryableError, match="現行source_policy"):
        adapter.get(f"https://{host}/image")
    assert not calls


def test_Openverseの元ページ照合もMapillary無効化に従う(setup):  # noqa: F811
    fixture = json.loads(FIXTURE.read_text())
    selected = fixture["results"][0]
    selected["foreign_landing_url"] = "https://www.mapillary.com/app/?pKey=123"
    selected["url"] = "https://images.mapillary.com/123.jpg"
    calls = []

    def opener(request, **kwargs):
        calls.append(request.full_url)
        assert request.full_url.startswith(ENDPOINT)
        return Response({"results": [selected]})

    disable()
    adapter = OpenverseAdapter(load_policy(ROOT / "configs/source_policy.yaml", "openverse"),
                               opener=opener)
    result = adapter.search(SearchRequest("openverse", "castle"))
    assert result.candidates[0].exclusion_reason == "source_license_or_author_unverified"
    assert len(calls) == 1


def test_redirect後も現行無効化を再照合する(setup):  # noqa: F811
    policy = load_policy(ROOT / "configs/source_policy.yaml", "openverse")
    calls = []

    def opener(request, **kwargs):
        calls.append(request.full_url)
        disable()
        raise HTTPError(ENDPOINT, 302, "fixture", {
            "Location": "https://www.mapillary.com/app/?pKey=123"}, None)

    adapter = HttpClient(policy, opener=opener)
    with pytest.raises(NonRetryableError):
        adapter.get(ENDPOINT)
    assert len(calls) == 1


def test_レート待機中の無効化も送信直前に拒否する(setup):  # noqa: F811
    clock = Clock()
    calls = []

    def wait(delay):
        clock.wait(delay)
        disable()

    adapter = HttpClient(setup, opener=lambda *args, **kwargs: calls.append(args),
                         clock=clock.clock, wait=wait)
    adapter._wait_for_slot("https://graph.mapillary.com/images")
    with pytest.raises(NonRetryableError):
        adapter.get("https://graph.mapillary.com/images")
    assert not calls


def test_過去enabledジョブをprepare時の現行無効化で拒否する(setup, tmp_path):  # noqa: F811
    payload, digest = payload_for(tmp_path)
    payload.update(policy=setup, request=asdict(
        SearchRequest("mapillary", "kyoto-street-buildings")))
    disable()
    with pytest.raises(NonRetryableError, match="現行source_policy"):
        stage.prepare(claim_for(payload, digest), database_url="sqlite://")


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="隔離PostgreSQL")
@pytest.mark.parametrize("code", [401, 403])
def test_認証拒否はspawn経由でも一試行で失敗し再取得できない(
    setup, queue, tmp_path, code,  # noqa: F811
):
    from sqlalchemy.orm import Session

    job_id = queue.enqueue("collect", None, f"{code:064x}",
                           {"policy": setup, "http_status": code})
    worker = Worker(queue, {"collect": "tests.mapillary_handler"}, tmp_path / "stop")
    worker.run(once=True)
    with Session(queue.engine) as session:
        job = session.get(Job, job_id)
        assert job.status == "failed" and job.attempts == 1
        assert f"HTTP {code}" in job.failure_reason
        assert "NonRetryableError" in job.failure_reason
    assert queue.claim(["collect"]) is None
