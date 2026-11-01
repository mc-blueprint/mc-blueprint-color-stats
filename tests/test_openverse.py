import io
import json
from pathlib import Path
from urllib.request import Request

import pytest

from colorstats.collect import SearchRequest
from colorstats.collect.openverse import ENDPOINT, OpenverseAdapter
from colorstats.collect.policy import load_policy
from colorstats.collect.stage import enqueue_collect

FIXTURE = Path(__file__).parent / "fixtures" / "openverse.json"
POLICY = Path(__file__).parents[1] / "configs" / "source_policy.yaml"


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
            return Response(
                f"{first['creator']} {first['license']} {first['license_url']}".encode()
            )
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
