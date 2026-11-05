import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from colorstats.schema.models import Asset, ProcessingRun, Subject
from colorstats.stats.subject_attributes import execute as derive_attributes
from colorstats.stats.supplement import execute
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue
from tests.test_stats_supplement import RULES
from tests.test_subjects_attributes import rules as rules
from tests.test_subjects_attributes_db import Catalog

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="隔離PostgreSQL専用",
)


def test_readonly_apply_preservation_and_retry(queue, asset, tmp_path):
    with Session(queue.engine) as session, session.begin():
        row = session.get(Asset, asset)
        row.scene_attributes = {"time_of_day": "night"}
        row.collected_location = "35,139"
        row.quality = {"marker": "保持", "metadata": {"extmetadata": {
            "DateTimeOriginal": {"value": "2020-07-01 12:00:00", "source": "exif"}}}}

    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(queue.engine, "before_cursor_execute", record)
    dry = execute(queue.engine, RULES, tmp_path / "dry.json", code_version="test")
    event.remove(queue.engine, "before_cursor_execute", record)
    assert any("READ ONLY" in s for s in statements)
    assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                   for s in statements)
    assert dry["attribute_changes"] == {"season": 1}
    with pytest.raises(ValueError, match="計画"):
        execute(queue.engine, RULES, tmp_path / "wrong.json", code_version="test",
                dry_run=False, expected_hash="wrong")
    assert not (tmp_path / "wrong.json").exists()
    first = execute(queue.engine, RULES, tmp_path / "apply.json", code_version="test",
                    dry_run=False, expected_hash=dry["plan_hash"])
    with Session(queue.engine) as session:
        row = session.get(Asset, asset)
        assert row.scene_attributes == {"season": "summer", "time_of_day": "night"}
        assert row.quality["marker"] == "保持"
        assert row.quality["scene_inference"]["run_id"] == first["run_id"]
        assert len(session.scalars(select(ProcessingRun)).all()) == 1
    retry = execute(queue.engine, RULES, tmp_path / "retry.json", code_version="test")
    assert retry["changes"] == 0
    execute(queue.engine, RULES, tmp_path / "retry-apply.json", code_version="test",
            dry_run=False, expected_hash=retry["plan_hash"])
    with Session(queue.engine) as session:
        assert len(session.scalars(select(ProcessingRun)).all()) == 1
    assert json.loads(Path(tmp_path / "apply.json").read_text())["changes"] == 1


def test_terrain_attributes_reuse_claim_rules(queue, asset, rules, tmp_path):
    with Session(queue.engine) as session, session.begin():
        terrain = Subject(name="地形", domain="real_terrain", scene_attributes={},
                          taxonomy_version="0.1.0")
        session.add(terrain)
        session.flush()
        session.get(Asset, asset).subject_id = terrain.id
        session.add(ProcessingRun(
            stage="subject", license_class="open", config_hash="a" * 64,
            parameters={"method": "saved-evidence-v1", "subject_keys": [{
                "domain": "real_terrain", "key": "test", "subject_id": str(terrain.id),
                "wikidata_id": "Q100"}]}, code_version="test", taxonomy_version="0.1.0",
            node="test", finished_at=datetime.now(UTC)),
        )
    result = derive_attributes(queue.engine, rules, Catalog(), tmp_path / "terrain.json",
                               code_version="test", dry_run=True,
                               domains=("real_building", "real_terrain"))
    assert result["counts"]["region"] == {"confirmed": 1, "unknown": 0}
    assert result["counts"]["era"] == {"confirmed": 1, "unknown": 0}


def test_correction_is_owned_atomic_and_idempotent(queue, asset, tmp_path):
    with Session(queue.engine) as session, session.begin():
        row = session.get(Asset, asset)
        row.collected_location = "35,0"
        row.scene_attributes = {"weather": "clear"}
        row.quality = {"metadata": {"extmetadata": {"DateTimeOriginal": {
            "value": "2020-07-01 12:00:00", "source": "exif"}}}}
    dry = execute(queue.engine, RULES, tmp_path / "initial-dry.json", code_version="test")
    initial = execute(queue.engine, RULES, tmp_path / "initial.json", code_version="test",
                      dry_run=False, expected_hash=dry["plan_hash"])
    references = [initial["run_id"]]
    evidence = {"a" * 64: {"date": "2020:12:01 12:00:00"}}
    corrected = execute(queue.engine, RULES, tmp_path / "correct-dry.json", code_version="test",
                        correction_runs=references, image_evidence=evidence)
    assert corrected["withdrawn_attributes"] == {"season": 1}
    assert corrected["changes"] == 1
    with Session(queue.engine) as session:
        assert session.get(Asset, asset).scene_attributes["season"] == "summer"
    execute(queue.engine, RULES, tmp_path / "correct.json", code_version="test", dry_run=False,
            expected_hash=corrected["plan_hash"], correction_runs=references,
            image_evidence=evidence)
    retry = execute(queue.engine, RULES, tmp_path / "repeat.json", code_version="test",
                    correction_runs=references, image_evidence=evidence)
    assert retry["changes"] == 0
    with Session(queue.engine) as session, session.begin():
        row = session.get(Asset, asset)
        assert row.scene_attributes == {"weather": "clear"}
        row.scene_attributes = dict(row.scene_attributes, season="spring")
        row.quality = dict(row.quality, scene_inference={"method": "other", "run_id": "other"})
    protected = execute(queue.engine, RULES, tmp_path / "protected.json", code_version="test",
                        correction_runs=references, image_evidence=evidence)
    assert protected["changes"] == 0


def test_painting_does_not_gain_terrain_attributes(queue, asset, tmp_path):
    with Session(queue.engine) as session, session.begin():
        row = session.get(Asset, asset)
        row.domain = "real_terrain"
        row.quality = {"metadata": {"categories": [
            {"title": "Category:Forests in Norway in autumn"},
            {"title": "Category:Paintings of forests"}]}}
    result = execute(queue.engine, RULES, tmp_path / "painting.json", code_version="test")
    assert result["changes"] == 0
    assert result["assets"][0]["after"] == {}
