import copy
import hashlib
import io
import json
import os
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from colorstats.collect import SearchRequest
from colorstats.collect.commons import CommonsAdapter
from colorstats.collect.policy import check_policy, license_class, load_policy
from colorstats.collect.stage import enqueue_collect, prepare, register
from colorstats.queue import Claim
from colorstats.queue.worker import Worker
from colorstats.schema.models import Asset, Job, ProcessingRun, Source
from tests.test_queue import database, queue  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
RECORDED = json.loads((ROOT / "tests/fixtures/commons.json").read_text(encoding="utf-8"))


class Response(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(json.dumps(data).encode() if isinstance(data, dict) else data)
        self.headers = headers or {}


class Clock:
    def __init__(self):
        self.now = 0
        self.waits = []

    def clock(self):
        return self.now

    def wait(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


@pytest.fixture
def policy():
    return load_policy(ROOT / "configs/source_policy.yaml", "wikimedia_commons")


def adapter_for(policy, responses):
    clock = Clock()
    requests = []
    responses = iter(responses)

    def opener(request, **kwargs):
        requests.append((request, clock.now))
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    return CommonsAdapter(policy, opener=opener, clock=clock.clock, wait=clock.wait), requests


def responses():
    return [Response(record) for record in RECORDED]


def test_記録レスポンスからメタデータと選ばれ方を保持する(policy, tmp_path):
    adapter, requests = adapter_for(policy, responses() + [Response(b"original")])
    request = SearchRequest(
        "wikimedia_commons", "姫路城", "ja", page=3, offset=17, limit=1, stratum="japan-castle"
    )
    result = adapter.search(request)
    candidate = result.candidates[0]
    assert candidate.author == "Martin Falbisoner"
    assert candidate.license == "cc-by-sa-4.0"
    assert candidate.license_url == "https://creativecommons.org/licenses/by-sa/4.0"
    assert candidate.width == 5179 and candidate.height == 2688
    assert candidate.location == "34.839459, 134.693584"
    assert "Himeji Castle" in candidate.description and "<a" not in candidate.description
    assert (candidate.rank, candidate.page) == (17, 3)
    assert result.next_offset == 1
    assert result.parameters["sroffset"] == 17 and result.parameters["uselang"] == "ja"
    assert result.parameters["endpoint"] == "https://commons.wikimedia.org/w/api.php"
    assert result.parameters["rank_basis"] == {
        "base": 0,
        "scope": "search",
        "calculation": "sroffset + index",
    }
    assert result.parameters["page_basis"]["value"] == 3
    assert parse_qs(urlsplit(requests[0][0].full_url).query)["srsort"] == ["relevance"]
    assert parse_qs(urlsplit(requests[1][0].full_url).query)["iiextmetadatalanguage"] == ["ja"]
    adapter.download(candidate, tmp_path / "original")
    assert (tmp_path / "original").read_bytes() == b"original"
    assert [time for _, time in requests] == [0, 1, 2]
    assert all(r.get_header("User-agent") == policy["user_agent"] for r, _ in requests)
    adapter.finish()
    assert adapter.clock() == 3


def test_共通ポリシーはmaxlagを要求せずCommonsは通信前に検証する(policy):
    policy.pop("maxlag")
    check_policy(policy)
    with pytest.raises(ValueError, match="maxlag"):
        adapter_for(policy, [])


@pytest.mark.parametrize("specified", [None, "<b>指定クレジット</b>"])
def test_帰属表示は指定を優先し未指定なら作者とCreditを使う(policy, specified):
    recorded = copy.deepcopy(RECORDED)
    ext = recorded[1]["query"]["pages"][0]["imageinfo"][0]["extmetadata"]
    if specified:
        ext["Attribution"] = {"value": specified}
        ext.pop("Artist")
    adapter, _ = adapter_for(policy, [Response(record) for record in recorded])
    candidate = adapter.search(SearchRequest("wikimedia_commons", "castle")).candidates[0]
    assert candidate.exclusion_reason is None
    prefix = "指定クレジット" if specified else "Martin Falbisoner | Own work"
    assert candidate.attribution == (
        f"{prefix} | {candidate.source_url} | CC BY-SA 4.0 | "
        "https://creativecommons.org/licenses/by-sa/4.0 | 原本・改変なし"
    )


@pytest.mark.parametrize(
    "missing,reason",
    [
        ("Artist", "author_or_attribution"),
        ("LicenseShortName", "license_name"),
        ("LicenseUrl", "license_url"),
    ],
)
@pytest.mark.parametrize("required", ["true", "false", None])
def test_帰属必須情報不足はフラグ欠落や偽でも取得しない(
    policy, tmp_path, monkeypatch, caplog, missing, reason, required
):
    recorded = copy.deepcopy(RECORDED)
    ext = recorded[1]["query"]["pages"][0]["imageinfo"][0]["extmetadata"]
    ext.pop(missing)
    if required is None:
        ext.pop("AttributionRequired")
    else:
        ext["AttributionRequired"]["value"] = required
    adapter, requests = adapter_for(policy, [Response(record) for record in recorded])
    monkeypatch.setattr("colorstats.collect.stage.CommonsAdapter", lambda policy: adapter)
    payload, config_hash = payload_for(tmp_path)
    with caplog.at_level("INFO"):
        prepared = prepare(claim_for(payload, config_hash))
    assert prepared.files == [] and prepared.data["records"] == []
    assert prepared.info.parameters["skipped"][0]["reason"] == f"missing_attribution:{reason}"
    assert f"missing_attribution:{reason}" in caplog.text
    assert len(requests) == 2
    direct, calls = adapter_for(policy, [Response(record) for record in recorded])
    candidate = direct.search(SearchRequest("wikimedia_commons", "castle")).candidates[0]
    with pytest.raises(ValueError, match="missing_attribution"):
        direct.download(candidate, tmp_path / "denied")
    assert len(calls) == 2 and not (tmp_path / "denied").exists()


@pytest.mark.parametrize("license_name", ["pd", "cc0"])
def test_PDとCC0は帰属情報なしでも取得できる(policy, tmp_path, license_name):
    recorded = copy.deepcopy(RECORDED)
    info = recorded[1]["query"]["pages"][0]["imageinfo"][0]
    info["extmetadata"] = {
        "License": {"value": license_name},
        "AttributionRequired": {"value": "false"},
    }
    adapter, _ = adapter_for(policy, [Response(r) for r in recorded] + [Response(b"pd")])
    candidate = adapter.search(SearchRequest("wikimedia_commons", "castle")).candidates[0]
    assert candidate.exclusion_reason is None
    adapter.download(candidate, tmp_path / "original")
    assert (tmp_path / "original").read_bytes() == b"pd"


def test_実応答の複数ライセンスからCommonsMetadataの選択を採用する(policy, tmp_path):
    recorded = json.loads((ROOT / "tests/fixtures/commons-multilicense.json").read_text("utf-8"))
    adapter, _ = adapter_for(policy, [Response(r) for r in recorded] + [Response(b"original")])
    candidate = adapter.search(
        SearchRequest("wikimedia_commons", 'intitle:"Example.jpg"', limit=1)
    ).candidates[0]
    selection = candidate.metadata["license_selection"]
    assert selection["selected"] == candidate.license == "pd"
    assert selection["method"] == "CommonsMetadata"
    assert "Category:GFDL-en" in selection["candidates"]
    assert "Category:CC-BY-SA-3.0-migrated-with-disclaimers" in selection["candidates"]
    adapter.download(candidate, tmp_path / "original")
    assert (tmp_path / "original").read_bytes() == b"original"


def test_ライセンス候補カテゴリは継続応答も保持する(policy):
    recorded = copy.deepcopy(RECORDED)
    recorded[1]["query"]["pages"][0]["categories"] = [{"title": "Category:CC-BY-SA-4.0"}]
    recorded[1]["continue"] = {"clcontinue": "1|GFDL", "continue": "||"}
    continuation = {"query": {"pages": [{"categories": [{"title": "Category:GFDL"}]}]}}
    adapter, requests = adapter_for(policy, [Response(r) for r in recorded + [continuation]])
    candidate = adapter.search(SearchRequest("wikimedia_commons", "castle")).candidates[0]
    assert candidate.metadata["license_selection"]["candidates"] == [
        "Category:CC-BY-SA-4.0",
        "Category:GFDL",
    ]
    assert parse_qs(urlsplit(requests[-1][0].full_url).query)["clcontinue"] == ["1|GFDL"]
    assert parse_qs(urlsplit(requests[-1][0].full_url).query)["prop"] == ["categories"]


@pytest.mark.parametrize(
    "name, expected",
    [
        ("cc0", "open"),
        ("pd", "open"),
        ("CC-BY-4.0", "open"),
        ("cc-by-sa-4.0", "open"),
        ("cc-by-nd-4.0", "restricted"),
        ("cc-by-nc-4.0", "restricted"),
        ("unknown", "restricted"),
        ("cc-by-4.0; custom", "restricted"),
    ],
)
def test_完全一致のライセンス規則で未知とNDを拒否する(policy, name, expected):
    assert license_class(policy, name) == expected


def test_取得禁止とポリシー欠落では通信しない(policy, tmp_path):
    with pytest.raises(ValueError):
        load_policy(ROOT / "configs/source_policy.yaml", "unknown")
    with pytest.raises(ValueError):
        CommonsAdapter({**policy, "enabled": False})
    adapter, requests = adapter_for(policy, responses())
    candidate = adapter.search(SearchRequest("wikimedia_commons", "castle")).candidates[0]
    with pytest.raises(ValueError, match="restricted"):
        adapter.download(replace(candidate, license="cc-by-nd-4.0"), tmp_path / "denied")
    assert len(requests) == 2 and not (tmp_path / "denied").exists()


@pytest.mark.parametrize("failure", ["429", "503", "maxlag", "ratelimited"])
def test_負荷制限のRetryAfterと指数待機を守る(policy, failure):
    def error():
        if failure.isdigit():
            return HTTPError(
                "https://commons.wikimedia.org", int(failure), "busy", {"Retry-After": "12"}, None
            )
        return Response({"error": {"code": failure}}, {"Retry-After": "12"})

    adapter, requests = adapter_for(policy, [error(), error()] + responses())
    adapter.search(SearchRequest("wikimedia_commons", "castle"))
    assert [time for _, time in requests] == [0, 12, 24, 25]


def test_負荷制限の最終試行も待機してから失敗する(policy):
    adapter, requests = adapter_for(
        policy, [Response({"error": {"code": "maxlag"}}) for _ in range(3)]
    )
    with pytest.raises(RuntimeError, match="負荷制限"):
        adapter.search(SearchRequest("wikimedia_commons", "castle"))
    assert [time for _, time in requests] == [0, 5, 15]
    assert adapter.clock() == 35


def test_恒久APIエラーは再試行しない(policy):
    adapter, requests = adapter_for(policy, [Response({"error": {"code": "badvalue"}})])
    with pytest.raises(RuntimeError, match="badvalue"):
        adapter.search(SearchRequest("wikimedia_commons", "castle"))
    assert len(requests) == 1


def test_HTTP日時のRetryAfterを守る(policy, monkeypatch):
    class FixedDateTime:
        @staticmethod
        def now(tz):
            return datetime(2026, 11, 1, tzinfo=UTC)

    monkeypatch.setattr("colorstats.collect.commons.datetime", FixedDateTime)
    adapter, requests = adapter_for(
        policy,
        [
            Response(
                {"error": {"code": "maxlag"}}, {"Retry-After": "Sun, 01 Nov 2026 00:00:30 GMT"}
            ),
            *responses(),
        ],
    )
    adapter.search(SearchRequest("wikimedia_commons", "castle"))
    assert [time for _, time in requests] == [0, 30, 31]


def test_短いHTTPボディを原本として受理しない(policy, tmp_path):
    adapter, _ = adapter_for(
        policy,
        responses()
        + [
            Response(b"short", {"Content-Length": "100"}),
        ],
    )
    candidate = adapter.search(SearchRequest("wikimedia_commons", "castle")).candidates[0]
    with pytest.raises(OSError, match="途中"):
        adapter.download(candidate, tmp_path / "original")


def payload_for(tmp_path):
    config = tmp_path / "storage.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "storage": {
                    "raw": [
                        {"host": "windows", "path": str(tmp_path / "raw")},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    class Queue:
        def enqueue(self, stage, asset_id, config_hash, payload):
            self.payload, self.hash = payload, config_hash
            assert stage == "collect" and asset_id is None
            return "job"

    recorder = Queue()
    enqueue_collect(
        recorder,
        SearchRequest("wikimedia_commons", "castle", stratum="castles"),
        policy_path=ROOT / "configs/source_policy.yaml",
        storage_config=config,
        host="windows",
        domain="real_building",
        code_version="test",
        taxonomy_version="0.1.0",
    )
    return recorder.payload, recorder.hash


def claim_for(payload, config_hash):
    return Claim(
        uuid.uuid4(), uuid.uuid4(), "collect", None, config_hash, payload, 1, datetime.now(UTC)
    )


def test_原本はハッシュ名の一時出力になりrestrictedは取得しない(policy, tmp_path, monkeypatch):
    payload, config_hash = payload_for(tmp_path)
    recorded = copy.deepcopy(RECORDED)
    recorded[0]["query"]["search"] *= 2
    restricted = copy.deepcopy(recorded[1])
    restricted["query"]["pages"][0]["imageinfo"][0]["extmetadata"]["License"]["value"] = "ND"
    adapter, requests = adapter_for(
        policy,
        [Response(recorded[0]), Response(recorded[1]), Response(restricted), Response(b"image")],
    )
    monkeypatch.setattr("colorstats.collect.stage.CommonsAdapter", lambda policy: adapter)
    seen = []

    def decide(request, candidate):
        seen.append(candidate.rank)

    prepared = prepare(claim_for(payload, config_hash), decide=decide)
    assert len(prepared.files) == 1 and len(prepared.data["records"]) == 1
    assert seen == [0]
    assert prepared.info.parameters["skipped"][0]["reason"] == "restricted"
    temporary, target = prepared.files[0]
    digest = hashlib.sha256(b"image").hexdigest()
    assert target.name == digest + ".jpg" and temporary.parent == target.parent
    assert temporary.read_bytes() == b"image" and not target.exists()
    assert len(requests) == 4


def test_取得前の順次採否で同じバッチ内の作者上限を守る(policy, tmp_path, monkeypatch):
    payload, config_hash = payload_for(tmp_path)
    recorded = copy.deepcopy(RECORDED)
    recorded[0]["query"]["search"] *= 2
    adapter, requests = adapter_for(
        policy,
        [Response(recorded[0]), Response(recorded[1]), Response(recorded[1]), Response(b"image")],
    )
    monkeypatch.setattr("colorstats.collect.stage.CommonsAdapter", lambda policy: adapter)
    authors = set()
    seen = []

    def decide(request, candidate):
        seen.append(candidate.rank)
        assert request.stratum == "castles"
        if candidate.author in authors:
            assert len(requests) == 4
            return "author_limit"
        assert len(requests) == 3
        authors.add(candidate.author)
        return None

    prepared = prepare(claim_for(payload, config_hash), decide=decide)
    assert seen == [0, 1]
    assert len(prepared.files) == 1 and len(requests) == 4
    assert prepared.info.parameters["skipped"][0]["reason"] == "author_limit"


def test_採否判断の例外でも取得済み一時原本を掃除する(policy, tmp_path, monkeypatch):
    payload, config_hash = payload_for(tmp_path)
    recorded = copy.deepcopy(RECORDED)
    recorded[0]["query"]["search"] *= 2
    adapter, _ = adapter_for(
        policy,
        [Response(recorded[0]), Response(recorded[1]), Response(recorded[1]), Response(b"image")],
    )
    monkeypatch.setattr("colorstats.collect.stage.CommonsAdapter", lambda policy: adapter)

    def decide(request, candidate):
        if candidate.rank == 1:
            raise RuntimeError("採否失敗")

    with pytest.raises(RuntimeError, match="採否失敗"):
        prepare(claim_for(payload, config_hash), decide=decide)
    assert not list((tmp_path / "raw").rglob("*.tmp"))


@pytest.mark.parametrize("after_first", [False, True])
def test_通信途中の失敗では原本一時ファイルを掃除する(
    policy,
    tmp_path,
    monkeypatch,
    after_first,
):
    payload, config_hash = payload_for(tmp_path)
    recorded = copy.deepcopy(RECORDED)
    original_responses = []
    metadata = [Response(recorded[1])]
    if after_first:
        recorded[0]["query"]["search"] *= 2
        metadata.append(Response(recorded[1]))
        original_responses.append(Response(b"first"))
    adapter, _ = adapter_for(
        policy,
        [
            Response(recorded[0]),
            *metadata,
            *original_responses,
            OSError("通信失敗"),
        ],
    )
    monkeypatch.setattr("colorstats.collect.stage.CommonsAdapter", lambda policy: adapter)
    with pytest.raises(OSError, match="通信失敗"):
        prepare(claim_for(payload, config_hash))
    assert not list((tmp_path / "raw").rglob("*.tmp"))


@pytest.mark.parametrize("category", ["noncommercial", "academic_only"])
def test_明示した内部利用区分をrunに伝播する(policy, tmp_path, monkeypatch, category):
    payload, config_hash = payload_for(tmp_path)
    policy["license_rules"][category] = ["internal-test"]
    payload["policy"] = policy
    recorded = copy.deepcopy(RECORDED)
    recorded[1]["query"]["pages"][0]["imageinfo"][0]["extmetadata"]["License"]["value"] = (
        "internal-test"
    )
    adapter, _ = adapter_for(
        policy, [Response(record) for record in recorded] + [Response(b"image")]
    )
    monkeypatch.setattr("colorstats.collect.stage.CommonsAdapter", lambda policy: adapter)
    prepared = prepare(claim_for(payload, config_hash))
    assert prepared.info.license_class == category
    assert prepared.data["records"][0]["license_class"] == category


def test_保存先変更は通信前に拒否する(tmp_path):
    payload, config_hash = payload_for(tmp_path)
    Path(payload["storage_config"]).write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="保存先設定"):
        prepare(claim_for(payload, config_hash))


@pytest.mark.parametrize("missing", [True, False])
def test_欠落した原本と非画像を候補から除外する(policy, missing):
    recorded = copy.deepcopy(RECORDED)
    info = recorded[1]["query"]["pages"][0]
    if missing:
        info.pop("imageinfo")
    else:
        info["imageinfo"][0]["mime"] = "application/pdf"
    adapter, _ = adapter_for(policy, [Response(record) for record in recorded])
    assert adapter.search(SearchRequest("wikimedia_commons", "castle")).candidates == []


def test_同じ内容の原本は一つの出力を共有する(policy, tmp_path, monkeypatch):
    payload, config_hash = payload_for(tmp_path)
    recorded = copy.deepcopy(RECORDED)
    recorded[0]["query"]["search"] *= 2
    adapter, _ = adapter_for(
        policy,
        [
            Response(recorded[0]),
            Response(recorded[1]),
            Response(recorded[1]),
            Response(b"image"),
            Response(b"image"),
        ],
    )
    monkeypatch.setattr("colorstats.collect.stage.CommonsAdapter", lambda policy: adapter)
    prepared = prepare(claim_for(payload, config_hash))
    assert len(prepared.files) == 1 and len(prepared.data["records"]) == 2
    assert prepared.data["records"][0]["target"] == prepared.data["records"][1]["target"]


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="CIのPostgreSQL専用")
@pytest.mark.parametrize("specified", [None, "指定された帰属"])
def test_キュー完了と同時に出典画像と確定原本の参照を登録する(
    queue,  # noqa: F811
    policy,
    tmp_path,
    monkeypatch,
    specified,
):
    payload, config_hash = payload_for(tmp_path)
    job_id = queue.enqueue("collect", None, config_hash, payload)
    claim = queue.claim(["collect"])
    recorded = copy.deepcopy(RECORDED)
    if specified:
        recorded[1]["query"]["pages"][0]["imageinfo"][0]["extmetadata"]["Attribution"] = {
            "value": specified
        }
    adapter, _ = adapter_for(policy, [Response(r) for r in recorded] + [Response(b"original")])
    monkeypatch.setattr("colorstats.collect.stage.CommonsAdapter", lambda policy: adapter)
    prepared = prepare(claim)
    run_id = queue.complete(
        claim,
        prepared.info,
        lambda session, run: register(session, run, prepared.data),
        prepared.files,
    )
    assert queue.complete(claim, prepared.info, lambda *_: pytest.fail("二重登録")) == run_id
    with Session(queue.engine) as session:
        source = session.scalars(select(Source)).one()
        asset = session.scalars(select(Asset)).one()
        run = session.get(ProcessingRun, run_id)
        assert session.get(Job, job_id).status == "succeeded"
        assert source.author == "Martin Falbisoner" and source.license_class == "open"
        assert source.policy == payload["policy"] and "creativecommons.org" in source.attribution
        assert source.attribution == asset.quality["attribution"]
        assert source.attribution.startswith(specified or "Martin Falbisoner | Own work")
        assert asset.search_parameters["effective"]["srsort"] == "relevance"
        assert asset.search_parameters["effective"]["rank_basis"]["scope"] == "search"
        assert asset.search_parameters["effective"]["endpoint"].startswith("https://commons.")
        assert asset.quality["metadata"]["license_selection"]["method"] == "CommonsMetadata"
        assert asset.source_id == source.id and asset.search_provider == "wikimedia_commons"
        assert asset.search_parameters["request"]["stratum"] == "castles"
        assert asset.storage_path == run.output_paths[str(prepared.files[0][1])]
        assert Path(asset.storage_path).read_bytes() == b"original"
        assert run.parameters["asset_ids"] == [str(asset.id)]
        assert asset.quality["metadata"]["width"] == 5179
        assert session.scalar(select(func.count()).select_from(Asset)) == 1
    # 同じ出典を再度登録してもsourceを共有し、各検索機会のassetを残す。
    with Session(queue.engine) as session, session.begin():
        register(session, session.get(ProcessingRun, run_id), prepared.data)
        assert session.scalar(select(func.count()).select_from(Source)) == 1
        assert session.scalar(select(func.count()).select_from(Asset)) == 2
    with queue.engine.begin() as connection:
        connection.execute(text("TRUNCATE job, processing_run, source, asset CASCADE"))


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="CIのPostgreSQL専用")
def test_spawnワーカーでcollectが実行される(queue, tmp_path):  # noqa: F811
    payload, config_hash = payload_for(tmp_path)
    job_id = queue.enqueue("collect", None, config_hash, payload)
    Worker(queue, {"collect": "tests.collect_handler"}, tmp_path / "stop").run(once=True)
    with Session(queue.engine) as session:
        job = session.get(Job, job_id)
        assert job.status == "succeeded", job.failure_reason
        asset = session.scalars(select(Asset)).one()
        assert Path(asset.storage_path).read_bytes() == b"original"
        run = session.get(ProcessingRun, job.run_id)
        assert run.parameters["asset_ids"] == [str(asset.id)]
