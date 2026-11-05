import io
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from colorstats.collect import SearchRequest
from colorstats.collect.http import NonRetryableMeasurementLimit
from colorstats.collect.openverse import ENDPOINT, OpenverseAdapter
from colorstats.collect.policy import load_policy
from colorstats.collect.stage import enqueue_collect, prepare, register
from colorstats.schema.models import Asset, ProcessingRun, Source
from tests.test_collect import Clock, claim_for, payload_for
from tests.test_collect import isolated_acquisition_check as isolated_acquisition_check
from tests.test_queue import database, queue  # noqa: F401

FIXTURE = Path(__file__).parent / "fixtures" / "openverse.json"
POLICY = Path(__file__).parents[1] / "configs" / "source_policy.yaml"


def source_page(item, **changes):
    image = {
        "@context": "https://schema.org",
        "@type": "ImageObject",
        "contentUrl": item["url"],
        "creator": {"@type": "Person", "name": item["creator"]},
        "license": item["license_url"],
        **changes,
    }
    return '<script type="application/ld+json">' + json.dumps(image) + '</script>'


class Response(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


def test_openverse_search_rechecks_source_page_and_downloads_only_verified(tmp_path):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    first, second = fixture["results"]
    calls = []

    def opener(request: Request, timeout):
        calls.append(request.full_url)
        if request.full_url.startswith(ENDPOINT):
            return Response(json.dumps(fixture).encode())
        if request.full_url == first["foreign_landing_url"]:
            return Response(source_page(first).encode())
        if request.full_url == second["foreign_landing_url"]:
            return Response(b"Different author and licence")
        return Response(b"image bytes")

    policy = load_policy(POLICY, "openverse")
    adapter = OpenverseAdapter(policy, opener=opener, wait=lambda _: None)
    result = adapter.search(SearchRequest("openverse", "Himeji Castle", limit=2))

    assert [candidate.rank for candidate in result.candidates] == [0, 1]
    assert result.candidates[0].source_url == first["foreign_landing_url"]
    assert result.candidates[0].exclusion_reason is None
    assert result.candidates[1].exclusion_reason == "source_license_or_author_unverified"
    assert result.next_offset == 2
    assert result.parameters["endpoint"] == ENDPOINT
    assert result.parameters["page_basis"]["api_value"] == 1

    target = tmp_path / "sample.jpg"
    adapter.download(result.candidates[0], target)
    assert target.read_bytes() == b"image bytes"
    with pytest.raises(ValueError, match="source_license_or_author_unverified"):
        adapter.download(result.candidates[1], tmp_path / "excluded.jpg")
    assert calls[-1] == first["url"]


def test_openverse_rejects_other_provider():
    adapter = OpenverseAdapter(load_policy(POLICY, "openverse"), wait=lambda _: None)
    with pytest.raises(ValueError, match="Openverse"):
        adapter.search(SearchRequest("wikimedia_commons", "castle"))


def test_LoC無効時はOpenverse経由のLoC元ページへ通信しない(monkeypatch):
    item = json.loads(FIXTURE.read_text(encoding="utf-8"))["results"][0]
    item["foreign_landing_url"] = "https://data.labs.loc.gov/free-to-use/item"
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        return Response(json.dumps({"results": [item]}).encode())

    monkeypatch.setenv("COLORSTATS_SOURCE_POLICY", str(POLICY))
    adapter = OpenverseAdapter(load_policy(POLICY, "openverse"), opener=opener)
    with pytest.raises(NonRetryableMeasurementLimit, match="LoC source policy"):
        adapter.search(SearchRequest("openverse", "castle", limit=1))
    assert len(calls) == 1 and calls[0].startswith(ENDPOINT)


def test_Openverseの元ページchallengeは候補除外にせず処理を停止する():
    item = json.loads(FIXTURE.read_text(encoding="utf-8"))["results"][0]
    item["foreign_landing_url"] = "https://example.test/item"
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        if request.full_url.startswith(ENDPOINT):
            return Response(json.dumps({"results": [item]}).encode())
        raise HTTPError(request.full_url, 403, "Forbidden", {"Cf-Mitigated": "challenge"}, None)

    policy = load_policy(POLICY, "openverse")
    policy["hosts"]["example.test"] = {"kind": "page"}
    adapter = OpenverseAdapter(policy, opener=opener)
    with pytest.raises(NonRetryableMeasurementLimit, match="Cloudflare challenge"):
        adapter.search(SearchRequest("openverse", "castle", limit=1))
    assert len(calls) == 2 and calls[1] == item["foreign_landing_url"]


def test_実際の検索元ページ原本の全経路で再試行する(tmp_path):
    item = json.loads(FIXTURE.read_text(encoding="utf-8"))["results"][0]
    clock, calls = Clock(), []

    def busy(code):
        return HTTPError("https://example.test", code, "busy", {"Retry-After": "12"}, None)

    responses = iter([
        busy(429), Response(json.dumps({"results": [item]}).encode()),
        busy(429), Response(source_page(item).encode()),
        busy(503), Response(b"image bytes"),
    ])

    def opener(request, **kwargs):
        calls.append((request.full_url, clock.now))
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    policy = load_policy(POLICY, "openverse")
    policy["hosts"]["example.test"] = {"kind": "page"}
    adapter = OpenverseAdapter(policy, opener=opener,
                              clock=clock.clock, wait=clock.wait)
    candidate = adapter.search(SearchRequest("openverse", "castle", limit=1)).candidates[0]
    adapter.download(candidate, tmp_path / "image")
    adapter.finish()
    assert [time for _, time in calls] == [0, 12, 12, 24, 24, 36]
    assert [url for url, _ in calls[2:4]] == [item["foreign_landing_url"]] * 2
    assert [url for url, _ in calls[4:]] == [item["url"]] * 2
    assert clock.now == 37 and (tmp_path / "image").read_bytes() == b"image bytes"


@pytest.mark.parametrize(
    "changes",
    [
        {"license": "https://creativecommons.org/licenses/by-nc/2.0/"},
        {"license": "https://creativecommons.org/licenses/by-nd/2.0/"},
        {"license": "https://creativecommons.org/licenses/by-sa/2.0/"},
        {"license": "https://creativecommons.org/licenses/by/4.0/"},
        {"license": "https://creativecommons.org.evil.test/licenses/by/2.0/"},
        {"license": "https://creativecommons.org/licenses/by/2.0/?custom=nc"},
        {"license": None},
        {"contentUrl": "https://example.test/another-image.jpg"},
        {"creator": "Dimitry Brown"},
        {"@type": "WebPage"},
        {"@context": "https://example.test/context"},
    ],
)
def test_対象画像の作者とライセンスが一致しなければ取得しない(tmp_path, changes):
    item = json.loads(FIXTURE.read_text(encoding="utf-8"))["results"][0]
    calls = []

    def opener(request, **kwargs):
        calls.append(request.full_url)
        if request.full_url.startswith(ENDPOINT):
            return Response(json.dumps({"results": [item]}).encode())
        # ページ全体には期待値があっても、対象画像の条件が異なれば除外する。
        page = source_page(item, **changes) + source_page(
            item, contentUrl="https://example.test/unrelated.jpg"
        ) + f"{item['creator']} {item['license_url']}"
        return Response(page.encode())

    adapter = OpenverseAdapter(
        load_policy(POLICY, "openverse"), opener=opener, wait=lambda _: None
    )
    candidate = adapter.search(SearchRequest("openverse", "castle", limit=1)).candidates[0]
    assert candidate.metadata["source_verification"]["status"] == "review"
    assert candidate.exclusion_reason == "source_license_or_author_unverified"
    with pytest.raises(ValueError, match="unverified"):
        adapter.download(candidate, tmp_path / "denied.jpg")
    assert len(calls) == 2 and not (tmp_path / "denied.jpg").exists()


@pytest.mark.parametrize("field,value", [("license", "by-sa"), ("license_version", "4.0"),
                                         ("license_version", None),
                                         ("license_version", "2.0/../by-nc/4.0")])
def test_APIの識別子と版とURLの不整合も取得しない(field, value):
    item = json.loads(FIXTURE.read_text(encoding="utf-8"))["results"][0]
    item[field] = value
    responses = iter([json.dumps({"results": [item]}), source_page(item)])
    adapter = OpenverseAdapter(
        load_policy(POLICY, "openverse"),
        opener=lambda *args, **kwargs: Response(next(responses).encode()),
        wait=lambda _: None,
    )
    candidate = adapter.search(SearchRequest("openverse", "castle", limit=1)).candidates[0]
    assert not candidate.metadata["source_verified"] and candidate.exclusion_reason


@pytest.mark.parametrize("name,version,path", [
    ("by", "2.0", "licenses/by"),
    ("by-sa", "4.0", "licenses/by-sa"),
    ("cc0", "1.0", "publicdomain/zero"),
    ("pdm", "1.0", "publicdomain/mark"),
])
def test_許可ライセンスの同一URL表記を照合する(name, version, path):
    item = json.loads(FIXTURE.read_text(encoding="utf-8"))["results"][0]
    item.update(license=name, license_version=version,
                license_url=f"https://creativecommons.org/{path}/{version}/")
    page = source_page(item, license={"@id": f"http://creativecommons.org/{path}/{version}"})
    responses = iter([json.dumps({"results": [item]}), page])
    adapter = OpenverseAdapter(
        load_policy(POLICY, "openverse"),
        opener=lambda *args, **kwargs: Response(next(responses).encode()),
        wait=lambda _: None,
    )
    candidate = adapter.search(SearchRequest("openverse", "castle", limit=1)).candidates[0]
    assert candidate.metadata["source_verified"] and candidate.exclusion_reason is None


@pytest.mark.parametrize("page_kind", ["text", "broken", "conflict", "graph"])
def test_構造化データがない場合と同一画像の矛盾を除外する(page_kind):
    item = json.loads(FIXTURE.read_text(encoding="utf-8"))["results"][0]
    page = {
        "text": f"{item['creator']} {item['license_url']}",
        "broken": '<script type="application/ld+json">{broken}</script>',
        "conflict": source_page(item) + source_page(
            item, license="https://creativecommons.org/licenses/by-nc/2.0/"
        ),
        "graph": '<script type="application/ld+json">' + json.dumps({
            "@context": "https://schema.org", "@graph": [{
                "@type": "ImageObject", "contentUrl": item["url"],
                "author": item["creator"], "license": item["license_url"],
            }],
        }) + '</script>',
    }[page_kind]
    responses = iter([json.dumps({"results": [item]}), page])
    adapter = OpenverseAdapter(
        load_policy(POLICY, "openverse"),
        opener=lambda *args, **kwargs: Response(next(responses).encode()),
        wait=lambda _: None,
    )
    candidate = adapter.search(SearchRequest("openverse", "castle", limit=1)).candidates[0]
    assert candidate.metadata["source_verified"] == (page_kind == "graph")


def review_adapter():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    first, second = fixture["results"]
    responses = iter([
        json.dumps(fixture).encode(),
        source_page(first, license="https://creativecommons.org/licenses/by-nc/2.0/").encode(),
        source_page(second).encode(),
        b"verified image",
    ])
    return OpenverseAdapter(
        load_policy(POLICY, "openverse"),
        opener=lambda *args, **kwargs: Response(next(responses)),
        wait=lambda _: None,
    )


def test_照合不一致は予約前に除外理由をrunへ残す(tmp_path, monkeypatch, caplog):
    payload, config_hash = payload_for(tmp_path)
    payload["request"]["provider"] = "openverse"
    payload["policy"] = load_policy(POLICY, "openverse")
    adapter = review_adapter()
    monkeypatch.setattr("colorstats.collect.stage.OpenverseAdapter", lambda policy: adapter)
    seen = []
    with caplog.at_level("INFO"):
        prepared = prepare(claim_for(payload, config_hash),
                           decide=lambda request, candidate: seen.append(candidate.rank))
    assert seen == [1] and len(prepared.files) == 1
    assert [r["candidate"]["rank"] for r in prepared.data["records"]] == [1]
    assert prepared.info.parameters["skipped"][0]["reason"] == "source_license_or_author_unverified"
    assert "source_license_or_author_unverified" in caplog.text
    prepared.files[0][0].unlink()


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="CIのPostgreSQL専用")
def test_NC不一致はassetとsourceへ登録されない(queue, tmp_path, monkeypatch):  # noqa: F811
    payload, config_hash = payload_for(tmp_path)
    payload["request"]["provider"] = "openverse"
    payload["policy"] = load_policy(POLICY, "openverse")
    queue.enqueue("collect", None, config_hash, payload)
    claim = queue.claim(["collect"])
    adapter = review_adapter()
    monkeypatch.setattr("colorstats.collect.stage.OpenverseAdapter", lambda policy: adapter)
    prepared = prepare(claim)
    run_id = queue.complete(claim, prepared.info,
                            lambda session, run: register(session, run, prepared.data),
                            prepared.files)
    with Session(queue.engine) as session:
        assert session.scalar(select(func.count()).select_from(Asset)) == 1
        assert session.scalar(select(func.count()).select_from(Source)) == 1
        asset = session.scalars(select(Asset)).one()
        assert asset.result_rank == 1 and asset.license_class == "open"
        assert session.get(ProcessingRun, run_id).parameters["skipped"][0]["rank"] == 0


def test_enqueue_accepts_openverse_provider(tmp_path):
    storage = tmp_path / "storage.yaml"
    storage.write_text("storage: {raw: []}\n", encoding="utf-8")

    class Queue:
        def enqueue(self, stage, asset_id, config_hash, payload):
            assert stage == "collect" and asset_id is None
            assert payload["request"]["provider"] == "openverse"
            assert payload["policy"]["min_interval"] == 1.0
            return "job"

    assert (
        enqueue_collect(
            Queue(),
            SearchRequest("openverse", "castle"),
            policy_path=POLICY,
            storage_config=storage,
            host="windows",
            domain="real_building",
            code_version="test",
            taxonomy_version="0.1.0",
        )
        == "job"
    )
