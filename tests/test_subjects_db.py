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
