import os
from pathlib import Path

import pytest
from sqlalchemy import delete, event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from colorstats.schema.models import Asset, ProcessingRun, Subject, SubjectCandidate
from colorstats.stats.subject_cli import load_rules
from colorstats.stats.subjects import execute
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="CIのPostgreSQL専用"
)
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def clear_subjects(queue):
    with Session(queue.engine) as session, session.begin():
        session.execute(delete(Subject))


def setup(queue, asset):
    with Session(queue.engine) as session, session.begin():
        a = session.get(Asset, asset)
        a.collected_title = "Dome of the Rock"
        a.quality = {"author": "保持する作者", "metadata": {
            "categories": [{"title": "Category:Facade of the Dome of the Rock"}],
        }}
    return load_rules(ROOT / "configs/subject_rules.yaml", ROOT / "taxonomy")


def counts(queue):
    with Session(queue.engine) as session:
        return [
            session.scalar(select(func.count()).select_from(model))
            for model in (Subject, SubjectCandidate, ProcessingRun)
        ]


def test_dry_run_commit_and_idempotent_retry(queue, asset, tmp_path):
    rules = setup(queue, asset)
    before = counts(queue)
    dry = execute(queue.engine, rules, tmp_path / "dry.json", code_version="test", dry_run=True)
    assert counts(queue) == before
    assert dry["counts"] == {"confirmed": 1, "candidate": 0, "unknown": 0}
    first = execute(queue.engine, rules, tmp_path / "first.json", code_version="test")
    after = counts(queue)
    second = execute(queue.engine, rules, tmp_path / "second.json", code_version="test")
    assert second["counts"] == first["counts"]
    assert counts(queue) == [after[0], after[1], after[2] + 1]
    assert second["assets"][0]["scene_attributes"] == first["assets"][0]["scene_attributes"]
    with Session(queue.engine) as session:
        a = session.get(Asset, asset)
        assert a.quality["author"] == "保持する作者"
        assert a.subject_id
        assert a.quality["subject_inference"]["state"] == "confirmed"
        candidate = session.scalar(select(SubjectCandidate).where(
            SubjectCandidate.asset_id == asset,
        ))
        assert candidate.evidence["run_id"] == second["run_id"]


def test_snapshot_failure_rolls_back_flushed_changes_and_retry(queue, asset, tmp_path):
    rules = setup(queue, asset)
    before = counts(queue)
    path = tmp_path / "existing.json"
    path.write_text("保持", encoding="utf-8")
    with pytest.raises(FileExistsError):
        execute(queue.engine, rules, path, code_version="test")
    assert counts(queue) == before
    with Session(queue.engine) as session:
        a = session.get(Asset, asset)
        assert a.subject_id is None
        assert a.scene_attributes == {}
        assert "subject_inference" not in a.quality
    assert path.read_text(encoding="utf-8") == "保持"
    assert execute(queue.engine, rules, tmp_path / "retry.json", code_version="test")["counts"] == {
        "confirmed": 1, "candidate": 0, "unknown": 0,
    }



def test_database_failure_has_no_partial_effect_and_retry(queue, asset, tmp_path):
    rules = setup(queue, asset)
    before = counts(queue)

    def fail(mapper, connection, target):
        connection.execute(text("SELECT 1 / 0"))

    event.listen(ProcessingRun, "before_insert", fail)
    try:
        with pytest.raises(DBAPIError):
            execute(queue.engine, rules, tmp_path / "failed.json", code_version="test")
    finally:
        event.remove(ProcessingRun, "before_insert", fail)
    assert counts(queue) == before
    with Session(queue.engine) as session:
        assert session.get(Asset, asset).subject_id is None
    assert not (tmp_path / "failed.json").exists()
    assert execute(queue.engine, rules, tmp_path / "retry.json", code_version="test")["counts"] == {
        "confirmed": 1, "candidate": 0, "unknown": 0,
    }


def test_reconsider_revokes_only_new_assignments_and_rollback_is_atomic(queue, asset, tmp_path):
    rules = setup(queue, asset)
    first = execute(queue.engine, rules, tmp_path / "first.json", code_version="test")
    with Session(queue.engine) as session, session.begin():
        a = session.get(Asset, asset)
        a.collected_title = "Strasbourg Cathedral"
        a.quality = {**a.quality, "metadata": {"categories": []}}
    path = tmp_path / "protected.json"
    path.write_text("既存出力", encoding="utf-8")
    with pytest.raises(FileExistsError):
        execute(queue.engine, rules, path, code_version="test", reconsider_run=first["run_id"])
    with Session(queue.engine) as session:
        assert str(session.get(Asset, asset).subject_id) == first["assets"][0]["subject_id"]
    dry = execute(
        queue.engine, rules, tmp_path / "dry.json", code_version="test",
        reconsider_run=first["run_id"], dry_run=True,
    )
    assert dry["revoked_assignments"] == dry["reconsidered_assignments"] == 1
    applied = execute(
        queue.engine, rules, tmp_path / "applied.json", code_version="test",
        reconsider_run=first["run_id"],
    )
    assert applied["revoked_assignments"] == 1
    with Session(queue.engine) as session:
        assert session.get(Asset, asset).subject_id is None
        assert session.get(Asset, asset).scene_attributes == {}
    retry = execute(queue.engine, rules, tmp_path / "retry.json", code_version="test")
    assert retry["counts"] == applied["counts"]


def test_reconsider_keeps_assignments_from_before_the_source_run(queue, asset, tmp_path):
    rules = setup(queue, asset)
    original = execute(queue.engine, rules, tmp_path / "original.json", code_version="test")
    preserved = execute(queue.engine, rules, tmp_path / "preserved.json", code_version="test")
    with Session(queue.engine) as session, session.begin():
        a = session.get(Asset, asset)
        a.collected_title = "別の対象"
        a.quality = {**a.quality, "metadata": {"categories": []}}
    result = execute(
        queue.engine, rules, tmp_path / "result.json", code_version="test",
        reconsider_run=preserved["run_id"],
    )
    assert result["reconsidered_assignments"] == result["revoked_assignments"] == 0
    assert result["preserved_prior_assignments"] == 1
    assert result["assets"][0]["subject_id"] == original["assets"][0]["subject_id"]

def test_wikidata_failure_rolls_back_and_keeps_confirmed(queue, asset, tmp_path):
    from urllib.error import URLError

    rules = setup(queue, asset)
    first = execute(queue.engine, rules, tmp_path / "first.json", code_version="test")
    before = counts(queue)

    class FailedCatalog:
        def build(self, categories, rules):
            raise URLError("API unavailable")

    with pytest.raises(URLError):
        execute(
            queue.engine, rules, tmp_path / "failed.json", code_version="test",
            wikidata=FailedCatalog(),
        )
    assert counts(queue) == before
    assert not (tmp_path / "failed.json").exists()
    with Session(queue.engine) as session:
        assert str(session.get(Asset, asset).subject_id) == first["assets"][0]["subject_id"]


def test_automatic_key_retry_and_reconsider_reuses_transaction(queue, asset, tmp_path):
    import copy

    rules = setup(queue, asset)

    class Catalog:
        def build(self, categories, rules):
            result = copy.deepcopy(rules)
            result["subjects"][2].update({
                "wikidata_id": "Q172077", "coordinates": [31.778, 35.235],
                "automatic_categories": ["facade of the dome of the rock"],
            })
            result["wikidata"] = {"requests": {"fixture": "saved-response-hash"}}
            return result

    first = execute(
        queue.engine, rules, tmp_path / "auto.json", code_version="test", wikidata=Catalog(),
    )
    assert first["origins"] == {"manual": 1}
    retry = execute(
        queue.engine, rules, tmp_path / "retry.json", code_version="test", wikidata=Catalog(),
    )
    assert retry["assets"][0]["subject_id"] == first["assets"][0]["subject_id"]
    with Session(queue.engine) as session:
        run = session.get(ProcessingRun, retry["run_id"])
        assert run.parameters["wikidata"] == first["wikidata"]
    with Session(queue.engine) as session, session.begin():
        a = session.get(Asset, asset)
        a.collected_title = "Unknown"
        a.quality = {**a.quality, "metadata": {"categories": []}}
    # 再実行runは新規付与でないため、初回run以前の確定を取り消さない。
    preserved = execute(
        queue.engine, rules, tmp_path / "preserved-auto.json", code_version="test",
        reconsider_run=retry["run_id"], wikidata=Catalog(),
    )
    assert preserved["preserved_prior_assignments"] == 1
    assert preserved["assets"][0]["subject_id"] == first["assets"][0]["subject_id"]

def test_new_wikidata_key_is_stable_and_can_be_revoked(queue, asset, tmp_path):
    rules = setup(queue, asset)
    rules["subjects"] = [{
        "key": "wikidata:Q172077", "name": "Dome of the Rock", "domain": "real_building",
        "aliases": ["Dome of the Rock"], "categories": ["Facade of the Dome of the Rock"],
        "automatic_categories": ["facade of the dome of the rock"],
        "coordinates": [31.778, 35.235], "wikidata_id": "Q172077", "attributes": {},
    }]
    first = execute(queue.engine, rules, tmp_path / "new-auto.json", code_version="test")
    assert first["origins"] == {"automatic": 1}
    assert first["confirmed_subjects"]["real_building"] == 1
    with Session(queue.engine) as session, session.begin():
        a = session.get(Asset, asset)
        a.collected_title = "Unknown"
        a.quality = {**a.quality, "metadata": {"categories": []}}
    revoked = execute(
        queue.engine, rules, tmp_path / "revoked-auto.json", code_version="test",
        reconsider_run=first["run_id"],
    )
    assert revoked["revoked_assignments"] == 1
    retry = execute(queue.engine, rules, tmp_path / "after-revoke.json", code_version="test")
    assert retry["assets"][0]["subject_id"] is None
    assert counts(queue)[0] == 1

@pytest.mark.parametrize("kind", ["category", "entity"])
def test_incomplete_api_response_preserves_confirmed_and_run(queue, asset, tmp_path, kind):
    from colorstats.stats.wikidata import WikidataCatalog

    rules = setup(queue, asset)
    first = execute(queue.engine, rules, tmp_path / "prior.json", code_version="test")
    before = counts(queue)

    class Client:
        policy = {"maxlag": 5}

        def _get(self, url):
            if "pageprops" in url:
                if kind == "category":
                    return {"query": {"pages": []}}
                return {"query": {"pages": [{
                    "title": "Category:Facade of the Dome of the Rock",
                    "pageprops": {"wikibase_item": "Q172077"},
                }]}}
            return {"entities": {}}

    catalog = WikidataCatalog({}, tmp_path / "cache", client=Client())
    # 欠損を検査する要求を一つに固定し、実際の取得経路から失敗させる。
    rules["subjects"] = []
    with pytest.raises(ValueError, match="欠損"):
        execute(
            queue.engine, rules, tmp_path / "partial.json", code_version="test", wikidata=catalog,
        )
    assert counts(queue) == before
    with Session(queue.engine) as session:
        assert str(session.get(Asset, asset).subject_id) == first["assets"][0]["subject_id"]
    assert not (tmp_path / "partial.json").exists()

def test_review_granularity_revokes_only_selected_run_and_blocks_sha_inheritance(
    queue, asset, tmp_path,
):
    import copy

    rules = setup(queue, asset)
    protected = execute(queue.engine, rules, tmp_path / "protected.json", code_version="test")
    with Session(queue.engine) as session, session.begin():
        a = session.get(Asset, asset)
        added = Asset(
            source_id=a.source_id, url=a.url + "?copy", sha256=a.sha256,
            storage_path=a.storage_path, domain=a.domain, license_class=a.license_class,
            retrieved_at=a.retrieved_at, taxonomy_version=a.taxonomy_version,
            scene_attributes={}, collected_title=a.collected_title,
            quality=copy.deepcopy(a.quality),
        )
        added.quality.pop("subject_inference", None)
        session.add(added)
        session.flush()
        added_id = added.id
    prior = execute(queue.engine, rules, tmp_path / "prior79.json", code_version="test")
    rules["subjects"][2].update({
        "wikidata_id": "Q172077", "candidate_only": True,
        "granularity": {"state": "coarse", "building_parts": ["Q700"]},
    })
    corrected = execute(
        queue.engine, rules, tmp_path / "review79.json", code_version="test",
        reconsider_run=prior["run_id"],
    )
    assert corrected["reconsidered_assignments"] == corrected["revoked_assignments"] == 1
    assert corrected["preserved_prior_assignments"] == 1
    rows = {r["asset_id"]: r for r in corrected["assets"]}
    assert rows[str(asset)]["subject_id"] == protected["assets"][0]["subject_id"]
    assert rows[str(added_id)]["subject_id"] is None
    assert "target_granularity" in rows[str(added_id)]["reasons"]
