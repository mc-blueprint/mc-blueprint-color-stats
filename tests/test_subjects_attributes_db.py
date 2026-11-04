import json
import os
import uuid
from pathlib import Path
from urllib.error import URLError

import pytest
from sqlalchemy import delete, event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from colorstats.schema.models import Asset, ProcessingRun, Subject
from colorstats.stats.subject_attributes import METHOD, execute
from colorstats.stats.subjects import METHOD as SUBJECT_METHOD
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue
from tests.test_subjects_attributes import entity
from tests.test_subjects_attributes import rules as rules

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="隔離PostgreSQL専用",
)


class Catalog:
    requests = {"fixture": "response-hash"}
    client = type("Client", (), {"policy": {"user_agent": "fixture"}})()

    def attribute_claims(self, ids):
        self.ids = set(ids)
        return {qid: entity() for qid in ids}


@pytest.fixture
def prepared(queue, asset):
    with Session(queue.engine) as session, session.begin():
        session.execute(delete(Subject))
        building = Subject(name="建築", domain="real_building", taxonomy_version="0.1.0",
                           scene_attributes={})
        terrain = Subject(name="地形", domain="real_terrain", taxonomy_version="0.1.0",
                          scene_attributes={})
        unbound = Subject(name="候補のみ", domain="real_building", taxonomy_version="0.1.0",
                          scene_attributes={})
        session.add_all([building, terrain, unbound])
        session.flush()
        sid = building.id
        a = session.get(Asset, asset)
        a.subject_id = sid
        a.collected_location = "35,139"
        session.add(ProcessingRun(
            stage="subject", license_class="open", config_hash="a" * 64,
            parameters={"method": SUBJECT_METHOD, "subject_keys": [{
                "subject_id": str(sid), "domain": "real_building", "wikidata_id": "Q100",
            }, {
                "subject_id": str(unbound.id), "domain": "real_building", "wikidata_id": "Q200",
            }]}, code_version="test", taxonomy_version="0.1.0", node="test",
            finished_at=session.scalar(select(text("clock_timestamp()"))),
        ))
    return sid


def state(queue):
    with Session(queue.engine) as session:
        return [(str(s.id), s.location, s.era, s.scene_attributes)
                for s in session.scalars(select(Subject).order_by(Subject.id))], [
            str(r.id) for r in session.scalars(select(ProcessingRun).order_by(ProcessingRun.id))
        ]


def test_dry_apply_retry_preserve_and_cancel(queue, prepared, rules, tmp_path):
    initial = state(queue)
    catalog = Catalog()
    dry = execute(queue.engine, rules, catalog, tmp_path / "dry.json",
                  code_version="test", dry_run=True)
    assert state(queue) == initial
    assert catalog.ids == {"Q100"}
    assert [r["subject_id"] for r in dry["subjects"]] == [str(prepared)]
    assert dry["counts"] == {k: {"confirmed": 1, "unknown": 0} for k in ("region", "era")}
    first = execute(queue.engine, rules, Catalog(), tmp_path / "first.json", code_version="test")
    after = state(queue)
    second = execute(queue.engine, rules, Catalog(), tmp_path / "second.json", code_version="test")
    assert second["counts"] == first["counts"]
    assert second["changes"] == []
    assert state(queue)[0] == after[0]
    cancelled = execute(queue.engine, rules, Catalog(), tmp_path / "cancel.json",
                        code_version="test", cancel_run=first["run_id"])
    assert cancelled["counts"] == {k: {"confirmed": 0, "unknown": 1} for k in ("region", "era")}
    assert state(queue)[0] == initial[0]
    retry = execute(queue.engine, rules, Catalog(), tmp_path / "retry.json", code_version="test")
    assert retry["counts"] == first["counts"]
    assert state(queue)[0] == after[0]


def test_confirmed_subject_without_wikidata_key_is_counted_unknown(
    queue, prepared, rules, tmp_path,
):
    with Session(queue.engine) as session, session.begin():
        for run in session.scalars(select(ProcessingRun)):
            run.parameters = {"method": SUBJECT_METHOD, "subject_keys": []}
    result = execute(queue.engine, rules, Catalog(), tmp_path / "unknown.json", code_version="test")
    assert result["counts"] == {k: {"confirmed": 0, "unknown": 1} for k in ("region", "era")}
    assert result["reasons"]["region"] == {"no_wikidata_identity": 1}


def test_cancel_old_run_removes_candidate_values_and_is_atomic(queue, prepared, rules, tmp_path):
    run_id = uuid.uuid4()
    path = tmp_path / "old.json"
    with Session(queue.engine) as session, session.begin():
        candidate = session.scalar(select(Subject).where(Subject.name == "候補のみ"))
        candidate.location, candidate.era = "japan", "early_modern"
        sid = str(candidate.id)
        path.write_text(json.dumps({
            "run_id": str(run_id), "dry_run": False, "subjects": [{
                "subject_id": sid, "before": {"region": None, "era": None},
                "after": {"region": "japan", "era": "early_modern"},
            }],
        }), encoding="utf-8")
        session.add(ProcessingRun(
            id=run_id, stage="subject", license_class="restricted", config_hash="a" * 64,
            parameters={"method": METHOD, "changes": [[sid, "region"], [sid, "era"]]},
            output_paths={"snapshot": str(path)}, code_version="old", taxonomy_version="0.1.0",
            node="test", finished_at=session.scalar(select(text("clock_timestamp()"))),
        ))
    before = state(queue)
    dry = execute(queue.engine, rules, Catalog(), tmp_path / "cancel-dry.json",
                  code_version="test", cancel_run=run_id, dry_run=True)
    assert len(dry["changes"]) == 2
    assert state(queue) == before
    protected = tmp_path / "protected.json"
    protected.write_text("保持", encoding="utf-8")
    with pytest.raises(FileExistsError):
        execute(queue.engine, rules, Catalog(), protected, code_version="test", cancel_run=run_id)
    assert state(queue) == before
    cancelled = execute(queue.engine, rules, Catalog(), tmp_path / "cancel-old.json",
                        code_version="test", cancel_run=run_id)
    assert cancelled["changes"] == [[sid, "region"], [sid, "era"]]
    with Session(queue.engine) as session:
        candidate = session.get(Subject, uuid.UUID(sid))
        assert candidate.location is candidate.era is None


def test_cancel_keeps_external_value_and_later_reapplication(queue, prepared, rules, tmp_path):
    first = execute(queue.engine, rules, Catalog(), tmp_path / "first.json", code_version="test")
    execute(queue.engine, rules, Catalog(), tmp_path / "cancel.json", code_version="test",
            cancel_run=first["run_id"])
    execute(queue.engine, rules, Catalog(), tmp_path / "reapply.json", code_version="test")
    with Session(queue.engine) as session, session.begin():
        session.get(Subject, prepared).era = "medieval"
    result = execute(queue.engine, rules, Catalog(), tmp_path / "old-cancel.json",
                     code_version="test", cancel_run=first["run_id"])
    row = next(r for r in result["subjects"] if r["subject_id"] == str(prepared))
    assert row["after"] == {"region": "japan", "era": "medieval"}
    assert result["changes"] == []


@pytest.mark.parametrize("failure", ["snapshot", "api", "database"])
def test_failure_is_atomic_and_preserves_existing(queue, prepared, rules, tmp_path, failure):
    with Session(queue.engine) as session, session.begin():
        session.get(Subject, prepared).location = "europe"
    before = state(queue)
    snapshot = tmp_path / "output.json"
    catalog = Catalog()
    expected = FileExistsError
    if failure == "snapshot":
        snapshot.write_text("保持", encoding="utf-8")
    elif failure == "api":
        def fail(ids):
            raise URLError("unavailable")
        catalog.attribute_claims = fail
        expected = URLError
    else:
        def fail_db(mapper, connection, target):
            connection.execute(text("SELECT 1 / 0"))
        event.listen(ProcessingRun, "before_insert", fail_db)
        expected = DBAPIError
    try:
        with pytest.raises(expected):
            execute(queue.engine, rules, catalog, snapshot, code_version="test")
    finally:
        if failure == "database":
            event.remove(ProcessingRun, "before_insert", fail_db)
    assert state(queue) == before
    result = execute(queue.engine, rules, Catalog(), tmp_path / "retry.json", code_version="test")
    row = next(r for r in result["subjects"] if r["subject_id"] == str(prepared))
    assert row["after"] == {"region": "europe", "era": "early_modern"}
    assert row["attributes"]["region"]["state"] == "preserved"


def test_invalid_cancel_run_is_rejected(queue, prepared, rules, tmp_path):
    before = state(queue)
    with pytest.raises(ValueError):
        execute(queue.engine, rules, Catalog(), tmp_path / "bad.json", code_version="test",
                cancel_run=uuid.uuid4())
    assert state(queue) == before
    assert not Path(tmp_path / "bad.json").exists()
