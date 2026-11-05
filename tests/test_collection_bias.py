import copy
import json
import math
import os
import random
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import sleep
from urllib.error import HTTPError

import pytest
import yaml
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from colorstats.collect import Candidate, SearchRequest, SearchResult, bias
from colorstats.collect.coverage import coverage, images
from colorstats.collect.policy import load_policy
from colorstats.collect.targets import load_targets, requests
from colorstats.queue import LeaseLost
from colorstats.schema.models import (
    Asset,
    CollectionReservation,
    Job,
    ProcessingRun,
    Source,
    Subject,
)
from tests.test_collect import payload_for
from tests.test_queue import INFO, database, expire  # noqa: F401
from tests.test_queue import queue as queue

ROOT = Path(__file__).resolve().parents[1]
DB = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="PostgreSQL専用")


@pytest.fixture
def config():
    result = load_targets(ROOT / "configs/collection_targets.yaml", ROOT / "taxonomy")
    result["strata"] = [result["strata"][0]]
    result["strata"][0]["subjects"] = 10
    result["strata"][0].pop("images")
    result["image_budget"] = 10
    result["limits"] = dict(
        subject_images=3, subject_share=1, author_share=1, source_share=1, region_share=1
    )
    return result


def candidate(index=0, author="作者"):
    return Candidate(
        source_url=f"https://example.test/{index}",
        original_url=f"https://example.test/{index}.png",
        rank=index,
        page=0,
        title=f"城{index} 外観",
        author=author,
        license="cc0",
        license_url=None,
        description=None,
        location="撮影地点",
        width=10,
        height=10,
        mime="image/png",
    )


def subjects(queue, count=2):
    with Session(queue.engine) as session, session.begin():
        session.execute(delete(Subject))
        for index in range(count):
            session.add(
                Subject(
                    name=f"城{index}",
                    domain="real_building",
                    location="japan",
                    era="early_modern",
                    taxonomy_version="0.1.0",
                    scene_attributes={
                        "style": "japanese",
                        "building_type": "castle",
                    },
                )
            )


def claims(queue, config, count=2):
    for index in range(count):
        queue.enqueue("collect", None, f"{index:064x}", {"bias": config})
    return [queue.claim(["collect"]) for _ in range(count)]


def request():
    return SearchRequest("wikimedia_commons", "城", stratum="japanese-castle")


def test_多言語と複数ページのランダム探索を再現できる(config):
    layer = config["strata"][0]
    first = list(requests(config, layer, random.Random(3)))
    assert first == list(requests(config, layer, random.Random(3)))
    assert first != list(requests(config, layer, random.Random(4)))
    assert {r.language for r in first} == {"ja", "en"}
    assert {r.page for r in first} == {0, 1, 2}
    for language in ("ja", "en"):
        assert len({r.start for r in first if r.language == language}) == 3
        assert next(r for r in first if r.language == language).start == 0


@pytest.mark.parametrize("key,value", [("style", "invalid"), ("era", ""), ("domain", "text")])
def test_層の語彙と必要属性を検証する(config, tmp_path, key, value):
    config["strata"][0]["attributes"][key] = value
    path = tmp_path / "targets.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError):
        load_targets(path, ROOT / "taxonomy")


@pytest.mark.parametrize("dimension", ["subject", "author", "source", "region"])
def test_各割合上限とsubject画像上限を適用する(config, dimension):
    config["limits"][f"{dimension}_share"] = 0.1
    row = dict(subject_id=uuid.uuid4(), author="a", source="s", region="r")
    layer = config["strata"][0]
    values = tuple(row.values())
    row["attributes"] = layer["attributes"]
    assert bias.quota_reason([], config, *values, layer) is None
    assert bias.quota_reason([row], config, *values, layer) == f"{dimension}_limit"
    config["limits"][f"{dimension}_share"] = 1
    config["limits"]["subject_images"] = 1
    assert bias.quota_reason([row], config, *values, layer) == "subject_limit"


def test_一万枚の集中枠はCommons八千枚で止まる():
    config = load_targets(ROOT / "configs/collection_targets.yaml", ROOT / "taxonomy")
    assert config["image_budget"] == 10000
    assert sum(layer["images"] for layer in config["strata"]) == 10000
    assert sum(int(layer["images"] * 0.8) for layer in config["strata"]) == 8000
    layer = config["strata"][0]
    row = dict(subject_id=None, author="", source="wikimedia_commons", region=None,
               attributes=layer["attributes"])
    values = (None, "", "wikimedia_commons", None, layer)
    quota = int(layer["images"] * config["limits"]["source_share"])
    assert bias.quota_reason([row] * (quota - 1), config, *values) is None
    assert bias.quota_reason([row] * quota, config, *values) == "stratum_source_limit"
    assert bias.quota_reason([row] * 8000, config, *values) == "source_limit"


@DB
def test_旧prepの空属性subjectを収集で再同定しない(queue, config):
    subjects(queue, 1)
    with Session(queue.engine) as session, session.begin():
        session.execute(update(Subject).values(scene_attributes={}))
    claim = claims(queue, config, 1)[0]
    assert bias.reserve(queue, claim, config, request(), candidate()) is None
    with Session(queue.engine) as session:
        assert session.scalars(select(CollectionReservation)).one().subject_id is None


@DB
def test_未同定でも画像目標で計画と予約を止める(queue, config, tmp_path):
    config["strata"][0]["images"] = 1
    claim = claims(queue, config, 1)[0]
    assert bias.reserve(queue, claim, config, request(), replace(candidate(), title="未知")) is None
    assert bias.reserve(queue, claim, config, request(), candidate(1)) == "image_target_reached"
    storage = tmp_path / "storage.yaml"
    storage.write_text("storage: {}", encoding="utf-8")
    assert bias.plan(queue, config, policy_path=ROOT / "configs/source_policy.yaml",
                     storage_config=storage, host="test", code_version="test") == []


@DB
def test_全件未同定でも画像不足率の高い層から計画する(queue, config, tmp_path):
    layer = config["strata"][0]
    layer["images"] = 10
    empty = copy.deepcopy(layer)
    empty["id"] = "empty"
    empty["attributes"]["region"] = "elsewhere"
    config["strata"].append(empty)
    claim = claims(queue, config, 1)[0]
    assert bias.reserve(queue, claim, config, request(), replace(candidate(), title="未知")) is None
    storage = tmp_path / "storage.yaml"
    storage.write_text("storage: {}", encoding="utf-8")
    ids = bias.plan(queue, config, policy_path=ROOT / "configs/source_policy.yaml",
                    storage_config=storage, host="test", code_version="test")
    with Session(queue.engine) as session:
        assert session.get(Job, ids[0]).payload["request"]["stratum"] == "empty"


@pytest.mark.parametrize("dimension", ["author", "source"])
def test_層内枠と全体枠の両方を守り他層だけで層内枠を消費しない(config, dimension):
    config["image_budget"] = 100
    config["limits"][f"{dimension}_share"] = 0.2
    layer = config["strata"][0]
    values = dict(subject_id=None, author="a", source="s", region=None)
    row = {**values, "attributes": layer["attributes"]}
    other = {**values, "attributes": {"domain": "real_terrain"}}
    assert bias.quota_reason([row], config, *values.values(), layer) is None
    assert bias.quota_reason([row] * 2, config, *values.values(), layer) == (
        f"stratum_{dimension}_limit"
    )
    assert bias.quota_reason([other] * 19, config, *values.values(), layer) is None
    assert bias.quota_reason([other] * 20, config, *values.values(), layer) == (
        f"{dimension}_limit"
    )


@DB
@pytest.mark.parametrize("dimension", ["author", "source"])
def test_層内枠も並行予約で超えない(queue, config, dimension):
    config["image_budget"] = 100
    config["limits"][f"{dimension}_share"] = 0.1
    workers = claims(queue, config)
    barrier = threading.Barrier(2)

    def decide(index):
        barrier.wait(timeout=5)
        return bias.reserve(queue, workers[index], config, request(), candidate(index))

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(decide, range(2)))
    assert result.count(None) == 1
    assert f"stratum_{dimension}_limit" in result


@DB
@pytest.mark.parametrize("bound", ["author", "subject", "source", "region", "target"])
def test_2ワーカーが同時に同じ層を判断しても上限を超えない(queue, config, bound):
    subjects(queue)
    if bound == "target":
        config["strata"][0]["images"] = 1
    else:
        config["limits"][f"{bound}_share"] = 0.1
    workers = claims(queue, config)
    barrier = threading.Barrier(2)

    def decide(index):
        barrier.wait(timeout=5)
        item = candidate(0 if bound == "subject" else index)
        return bias.reserve(queue, workers[index], config, request(), item)

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(decide, range(2)))
    if bound == "subject":
        assert result == [None, None]
        with Session(queue.engine) as session:
            assert all(r.subject_id is None for r in session.scalars(
                select(CollectionReservation)
            ))
        return
    assert result.count(None) == 1
    expected = "image_target_reached" if bound == "target" else f"{bound}_limit"
    assert expected in result
    with Session(queue.engine) as session:
        assert session.scalar(select(func.count()).select_from(CollectionReservation)) == 1


@DB
def test_不明候補も複数ワーカー間で画像予算を超えない(queue, config):
    config["image_budget"] = 1
    config["strata"] = [load_targets(ROOT / "configs/collection_targets.yaml")["strata"][2]]
    workers = claims(queue, config)
    barrier = threading.Barrier(2)
    terrain_request = replace(request(), stratum=config["strata"][0]["id"])

    def decide(index):
        barrier.wait(timeout=5)
        item = replace(candidate(index), title="森", author=None, location=None)
        return bias.reserve(queue, workers[index], config, terrain_request, item)

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(decide, range(2)))
    assert result.count(None) == 1 and "image_budget" in result


@DB
@pytest.mark.parametrize("failure", ["fail", "expire", "reclaim"])
def test_失敗と期限切れと新トークンで予約を回収する(queue, config, failure):
    subjects(queue)
    config["limits"]["author_share"] = 0.1
    old, current = claims(queue, config)
    assert bias.reserve(queue, old, config, request(), candidate()) is None
    if failure == "fail":
        queue.fail(old, "取得失敗")
    else:
        expire(queue, old)
        if failure == "reclaim":
            assert queue.claim(["collect"]).token != old.token
    assert bias.reserve(queue, current, config, request(), candidate(1)) is None
    with pytest.raises(LeaseLost):
        bias.reserve(queue, old, config, request(), candidate())
    with Session(queue.engine) as session:
        assert session.scalar(select(func.count()).select_from(CollectionReservation)) == 1


@DB
def test_未同定と曖昧なsubjectと作者不明も意図した層に採用する(queue, config):
    subjects(queue)
    claim = claims(queue, config, 1)[0]
    for index, title in enumerate(("知らない城", "城0 と 城1")):
        item = replace(candidate(index), title=title, author=None, location=None)
        assert bias.reserve(queue, claim, config, request(), item) is None
    with Session(queue.engine) as session:
        reservations = session.scalars(select(CollectionReservation)).all()
        assert len(reservations) == 2
        assert all(r.subject_id is None and r.author == "" for r in reservations)
        assert all(r.region == "japan" and r.region_basis == "stratum.region" for r in reservations)
        assert all(r.attributes == config["strata"][0]["attributes"] for r in reservations)
    assert (
        bias.reserve(
            queue, claim, config, request(), replace(candidate(2), title="Castle 0 exterior")
        )
        is None
    )


@DB
@pytest.mark.parametrize("basis", ["candidate.location", "stratum.region"])
def test_地域の優先順と判定根拠を記録する(queue, config, basis):
    subjects(queue)
    item = candidate()
    if basis != "subject.location":
        with Session(queue.engine) as session, session.begin():
            session.execute(update(Subject).values(location=None))
    if basis == "stratum.region":
        item = replace(item, location=None)
    claim = claims(queue, config, 1)[0]
    assert bias.reserve(queue, claim, config, request(), item) is None
    with Session(queue.engine) as session:
        reservation = session.scalars(select(CollectionReservation)).one()
        assert reservation.region_basis == basis
        assert reservation.region == ("撮影地点" if basis == "candidate.location" else "japan")


@DB
def test_名称一致だけではsubjectに画像上限を課さない(queue, config):
    subjects(queue)
    config["limits"]["subject_images"] = 1
    claim = claims(queue, config, 1)[0]
    assert bias.reserve(queue, claim, config, request(), candidate()) is None
    assert bias.reserve(queue, claim, config, request(), candidate(1)) is None
    with Session(queue.engine) as session:
        assert all(r.subject_id is None for r in session.scalars(
            select(CollectionReservation)
        ))


@DB
def test_未同定と不明群を上限から除外して登録とレポートに残す(
    queue, config, tmp_path, monkeypatch
):
    terrain = load_targets(ROOT / "configs/collection_targets.yaml")["strata"][2]
    config["strata"] = [terrain]
    for dimension in ("subject", "author", "region"):
        config["limits"][f"{dimension}_share"] = 0.1
    items = [replace(candidate(i), title="森", author=None, location=None) for i in range(3)]
    claim = prepared_job(queue, config, tmp_path, monkeypatch, Adapter(items))
    payload = copy.deepcopy(claim.payload)
    payload["request"]["stratum"] = terrain["id"]
    payload["domain"] = "real_terrain"
    claim = replace(claim, payload=payload)
    prepared = bias.prepare(claim)
    queue.complete(
        claim, prepared.info,
        lambda session, run: bias.register(session, run, prepared.data), prepared.files,
    )
    with Session(queue.engine) as session:
        assets = session.scalars(select(Asset)).all()
        assert len(assets) == 3
        for asset in assets:
            assert asset.subject_id is None
            assert asset.scene_attributes == {}
            evidence = asset.search_parameters["collection_bias"]
            assert evidence["intended_attributes"] == terrain["attributes"]
            assert evidence["region"] is None and evidence["region_basis"] == "unknown"
        layer = coverage(session, config)["strata"][0]
        assert layer["images"] == 3 and layer["subjects"] == 0
        assert layer["authors"] == 0 and layer["coverage"] == 0
        for dimension in ("subject", "author", "region"):
            assert layer[f"unknown_{dimension}_images"] == 3
            assert layer[f"unknown_{dimension}_share"] == 1
        assert layer["author_entropy_bits"] == 0
    assert bias.plan(
        queue, config, policy_path=ROOT / "configs/source_policy.yaml",
        storage_config=Path(claim.payload["storage_config"]), host="test", code_version="test",
    )


@DB
def test_期限切れでも完了中の予約を回収しない(queue, config):
    subjects(queue)
    config["limits"]["author_share"] = 0.1
    old, current = claims(queue, config)
    assert bias.reserve(queue, old, config, request(), candidate()) is None
    entered, release = threading.Event(), threading.Event()

    with queue.engine.begin() as connection:
        connection.execute(
            update(Job)
            .where(Job.id == old.id)
            .values(lease_until=func.clock_timestamp() + timedelta(seconds=0.5))
        )

    def register(session, run):
        entered.set()
        assert release.wait(4)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(queue.complete, old, INFO, register)
        assert entered.wait(3)
        try:
            sleep(0.6)
            # 完了取引がjobを所有している間は、回収側はSKIP LOCKEDで残す。
            assert bias.reserve(queue, current, config, request(), candidate(1)) == "author_limit"
        finally:
            release.set()
        future.result(timeout=5)


class Adapter:
    def __init__(self, items, *, fail=False):
        self.items, self.fail = items, fail
        self.downloaded = []

    def search(self, request):
        return SearchResult(self.items, {"test": True}, next_offset=30)

    def download(self, item, target):
        self.downloaded.append(item.source_url)
        if self.fail:
            raise OSError("模擬取得失敗")
        target.write_bytes(item.source_url.encode())

    def finish(self):
        pass


def prepared_job(queue, config, tmp_path, monkeypatch, adapter):
    payload, digest = payload_for(tmp_path)
    payload["request"]["stratum"] = "japanese-castle"
    payload["bias"] = config
    queue.enqueue("collect", None, digest, payload)
    claim = queue.claim(["collect"])
    monkeypatch.setenv("DATABASE_URL", queue.engine.url.render_as_string(hide_password=False))
    monkeypatch.setattr(bias.stage, "CommonsAdapter", lambda policy: adapter)
    return claim


@DB
def test_取得前に同一バッチの枠と目標を適用し成功取引で確定する(
    queue, config, tmp_path, monkeypatch
):
    subjects(queue)
    config["strata"][0]["images"] = 1
    adapter = Adapter([candidate(), candidate(1)])
    claim = prepared_job(queue, config, tmp_path, monkeypatch, adapter)
    prepared = bias.prepare(claim)
    assert len(adapter.downloaded) == 1
    assert prepared.info.parameters["skipped"][0]["reason"] == "image_target_reached"
    run_id = queue.complete(
        claim,
        prepared.info,
        lambda session, run: bias.register(session, run, prepared.data),
        prepared.files,
    )
    assert queue.complete(claim, prepared.info, lambda session, run: None) == run_id
    with Session(queue.engine) as session:
        reservation = session.scalars(select(CollectionReservation)).one()
        asset = session.get(Asset, reservation.asset_id)
        assert reservation.subject_id is None
        assert asset.subject_id is None
        assert Path(asset.storage_path).exists()
        report = coverage(session, config)
        assert report["strata"][0]["subjects"] == 0
        assert report["strata"][0]["unknown_subject_images"] == 1
    ids = bias.plan(
        queue,
        config,
        policy_path=ROOT / "configs/source_policy.yaml",
        storage_config=Path(claim.payload["storage_config"]),
        host="test",
        code_version="test",
    )
    assert ids == []


@DB
def test_原本取得失敗は予約と一時ファイルを解放する(queue, config, tmp_path, monkeypatch):
    subjects(queue)
    claim = prepared_job(queue, config, tmp_path, monkeypatch, Adapter([candidate()], fail=True))
    with pytest.raises(OSError, match="模擬取得失敗"):
        bias.prepare(claim)
    with Session(queue.engine) as session:
        assert session.scalar(select(func.count()).select_from(CollectionReservation)) == 0
        assert session.scalar(select(func.count()).select_from(Asset)) == 0


@DB
@pytest.mark.parametrize("status", [403, 404])
@pytest.mark.parametrize("all_skipped", [False, True])
def test_原本4xx除外は枠を即時解放し成功候補だけを確定する(
    queue, config, tmp_path, monkeypatch, status, all_skipped
):
    config["limits"]["source_share"] = 0.1
    adapter = Adapter([candidate(i) for i in range(3)])

    def download(item, target):
        adapter.downloaded.append(item.source_url)
        if all_skipped or item.rank != 1:
            target.write_bytes(b"partial")
            raise HTTPError(item.original_url, status, "除外", {}, None)
        target.write_bytes(b"original")

    adapter.download = download
    claim = prepared_job(queue, config, tmp_path, monkeypatch, adapter)
    prepared = bias.prepare(claim)
    assert len(adapter.downloaded) == (3 if all_skipped else 2)
    with Session(queue.engine) as session:
        assert session.scalar(select(func.count()).select_from(CollectionReservation)) == (
            0 if all_skipped else 1
        )
    run_id = queue.complete(
        claim, prepared.info,
        lambda session, run: bias.register(session, run, prepared.data), prepared.files,
    )
    with Session(queue.engine) as session:
        assert session.get(Job, claim.id).status == "succeeded"
        run = session.get(ProcessingRun, run_id)
        assert run.parameters["skipped"][0]["reason"] == f"download_http_{status}"
        assets = session.scalars(select(Asset)).all()
        reservations = session.scalars(select(CollectionReservation)).all()
        assert len(assets) == len(reservations) == (0 if all_skipped else 1)
        if assets:
            assert assets[0].url == candidate(1).original_url
            assert reservations[0].asset_id == assets[0].id
            assert Path(assets[0].storage_path).read_bytes() == b"original"
            assert run.parameters["skipped"][1]["reason"] == "source_limit"
    assert not list(tmp_path.rglob("*.tmp"))


@DB
def test_同じ出典URLも検索providerごとに予約と確定集計を揃える(
    queue, config, tmp_path, monkeypatch
):
    config["limits"]["source_share"] = 0.1
    item = candidate()
    claim = prepared_job(queue, config, tmp_path, monkeypatch, Adapter([item]))
    prepared = bias.prepare(claim)
    queue.complete(
        claim, prepared.info,
        lambda session, run: bias.register(session, run, prepared.data), prepared.files,
    )
    payload = copy.deepcopy(claim.payload)
    payload["request"]["provider"] = "openverse"
    payload["policy"] = load_policy(ROOT / "configs/source_policy.yaml", "openverse")
    queue.enqueue("collect", None, "b" * 64, payload)
    other = queue.claim(["collect"])
    monkeypatch.setattr(bias.stage, "OpenverseAdapter", lambda policy: Adapter([item]))
    prepared = bias.prepare(other)
    queue.complete(
        other, prepared.info,
        lambda session, run: bias.register(session, run, prepared.data), prepared.files,
    )
    with Session(queue.engine) as session:
        assert session.scalars(select(Source)).one().site == "wikimedia_commons"
        assert {row["source"] for row in images(session)} == {"wikimedia_commons", "openverse"}
        assert coverage(session, config)["strata"][0]["sources"] == 2
        assert {r.source for r in session.scalars(select(CollectionReservation))} == {
            "wikimedia_commons", "openverse"
        }
    current = claims(queue, config, 1)[0]
    for provider in ("wikimedia_commons", "openverse"):
        assert bias.reserve(
                queue, current, config,
                replace(request(), provider=provider, download_mode=None), candidate(1)
        ) == "source_limit"


@DB
def test_登録失敗は画像と予約確定を一緒に巻き戻す(queue, config, tmp_path, monkeypatch):
    subjects(queue)
    claim = prepared_job(queue, config, tmp_path, monkeypatch, Adapter([candidate()]))
    prepared = bias.prepare(claim)

    def broken(session, run):
        bias.register(session, run, prepared.data)
        session.flush()
        raise ValueError("登録失敗")

    with pytest.raises(ValueError, match="登録失敗"):
        queue.complete(claim, prepared.info, broken, prepared.files)
    with Session(queue.engine) as session:
        assert session.scalar(select(func.count()).select_from(Asset)) == 0
        assert session.scalars(select(CollectionReservation)).one().asset_id is None
    queue.fail(claim, "登録失敗")
    with queue._transaction() as session:
        session.execute(bias.LOCK_SQL)
        bias.reap(session)
    with Session(queue.engine) as session:
        assert session.scalar(select(func.count()).select_from(CollectionReservation)) == 0


@DB
@pytest.mark.parametrize("providers", [["wikimedia_commons"], ["wikimedia_commons", "openverse"]])
def test_計画は不足層だけを投入し同じ条件では重複しない(queue, config, tmp_path, providers):
    config["search"]["providers"] = providers
    storage = tmp_path / "storage.yaml"
    storage.write_text("storage: {}", encoding="utf-8")
    options = dict(
        policy_path=ROOT / "configs/source_policy.yaml",
        storage_config=storage,
        host="test",
        code_version="test",
        seed=9,
    )
    first = bias.plan(queue, config, **options)
    assert len(first) == 6 * len(providers)
    assert first == bias.plan(queue, config, **options)
    with Session(queue.engine) as session:
        jobs = session.scalars(select(Job)).all()
        assert {job.payload["request"]["provider"] for job in jobs} == set(providers)
        for job in jobs:
            if job.payload["request"]["provider"] == "openverse":
                assert "maxlag" not in job.payload["policy"]


@DB
@pytest.mark.parametrize("offset", [77, None, 900])
def test_成功runの継続位置をページ上限内で再計画する(queue, config, tmp_path, offset):
    storage = tmp_path / "storage.yaml"
    storage.write_text("storage: {}", encoding="utf-8")
    options = dict(
        policy_path=ROOT / "configs/source_policy.yaml",
        storage_config=storage,
        host="test",
        code_version="test",
        seed=9,
    )
    initial = bias.plan(queue, config, **options)
    claim = queue.claim(["collect"])
    assert claim.payload["request"]["page"] == 0
    queue.complete(
        claim, replace(INFO, parameters={"next_offset": offset}), lambda session, run: None
    )
    planned = bias.plan(queue, config, **options)
    added = set(planned) - set(initial)
    assert len(added) == (1 if offset == 77 else 0)
    if added:
        with Session(queue.engine) as session:
            request = session.get(Job, added.pop()).payload["request"]
        assert request["offset"] == 77 and request["page"] == 1


@DB
def test_1000枚の模擬データで網羅率と集中度を出力する(queue, config, tmp_path, monkeypatch):
    from colorstats.collect.bias_cli import main
    from colorstats.schema.models import Source

    config["image_budget"] = 1000
    config["limits"]["author_share"] = 0.5
    config["strata"][0]["subjects"] = 500
    empty = copy.deepcopy(config["strata"][0])
    empty["id"] = "empty"
    empty["attributes"]["region"] = "elsewhere"
    config["strata"].append(empty)
    subjects(queue, 500)
    with Session(queue.engine) as session, session.begin():
        catalog = session.scalars(select(Subject).order_by(Subject.name)).all()
        source = Source(
            url="https://example.test/pilot",
            site="fixture",
            author="a",
            license="cc0",
            license_class="open",
            retrieved_at=datetime.now(UTC),
            policy={},
        )
        session.add(source)
        session.flush()
        for index in range(1000):
            session.add(
                Asset(
                    source_id=source.id,
                    subject_id=catalog[index // 2].id,
                    url=f"https://example.test/{index}",
                    sha256=f"{index:064x}",
                    storage_path=f"fixture/{index}",
                    domain="real_building",
                    license_class="open",
                    retrieved_at=datetime.now(UTC),
                    taxonomy_version="0.1.0",
                    scene_attributes={},
                    quality={"author": "a" if index < 750 else "b"},
                )
            )
    with Session(queue.engine) as session:
        report = coverage(session, config)
    layer = report["strata"][0]
    assert (report["images"], layer["images"], layer["subjects"]) == (1000, 1000, 500)
    assert (layer["authors"], layer["sources"], layer["coverage"]) == (2, 1, 1)
    assert layer["top_author_share"] == 0.75
    assert layer["concentrated"]
    assert layer["author_entropy_bits"] == pytest.approx(
        -0.75 * math.log2(0.75) - 0.25 * math.log2(0.25)
    )
    assert report["strata"][1]["images"] == 0
    targets, output = tmp_path / "targets.yaml", tmp_path / "report.json"
    targets.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", queue.engine.url.render_as_string(hide_password=False))
    monkeypatch.setattr(
        "sys.argv",
        [
            "bias_cli",
            "--targets",
            str(targets),
            "--taxonomy",
            str(ROOT / "taxonomy"),
            "report",
            "--output",
            str(output),
        ],
    )
    main()
    assert json.loads(output.read_text(encoding="utf-8")) == report
