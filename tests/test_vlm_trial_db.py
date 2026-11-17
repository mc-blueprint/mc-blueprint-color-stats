import os
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from colorstats.schema.models import Asset, Retention, Source, Subject
from colorstats.trial_inputs import (
    prepare,
    read_candidates,
    read_session,
    recheck,
    select_candidates,
)
from tests.test_queue import database as database
from tests.test_queue import queue as queue
from tests.test_vlm_trial import candidates as candidates

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="隔離PostgreSQL専用"
)


@pytest.fixture
def trial(queue, candidates):
    rows, legacy, now = candidates
    source_id = uuid4()
    with Session(queue.engine) as session, session.begin():
        session.add(
            Source(
                id=source_id,
                url="https://example.test/trial",
                site="fixture",
                license="CC0",
                license_class="open",
                policy={},
                retrieved_at=now,
            )
        )
        session.flush()
        for row in rows:
            session.add(
                Subject(
                    id=UUID(row["subject_group"]),
                    name="合成の建物",
                    domain="real_building",
                    taxonomy_version="test",
                    scene_attributes={},
                )
            )
            session.flush()
            session.add(
                Asset(
                    id=UUID(row["asset_id"]),
                    source_id=source_id,
                    subject_id=UUID(row["subject_group"]),
                    url="https://example.test/" + row["asset_id"],
                    sha256=row["source_sha256"],
                    phash=row["phash"],
                    width=64,
                    height=48,
                    storage_path=row["path"],
                    domain="real_building",
                    license_class="open",
                    retrieved_at=now,
                    taxonomy_version="test",
                    quality={},
                    scene_attributes={},
                )
            )
            session.flush()
            session.add(
                Retention(
                    asset_id=UUID(row["asset_id"]),
                    expires_at=now + timedelta(days=3),
                    backup_until=now + timedelta(days=4),
                )
            )
    return queue.engine, rows, legacy, now, source_id


def test_実DB読取と合成選定準備再検査が本番形式の行を更新しない(trial, tmp_path):
    engine, reviews, legacy, now, _ = trial
    with Session(engine) as session:
        before = (
            session.execute(text("SELECT row_to_json(a)::text FROM asset a ORDER BY id"))
            .scalars()
            .all()
        )
    rows, pairs = read_candidates(engine, reviews, now=now)
    root = tmp_path / "private"
    prepare(select_candidates(rows, legacy, pairs, now=now), root, now=now)
    assert recheck(engine, root, now=now) == now + timedelta(hours=24)
    with Session(engine) as session:
        assert (
            session.execute(text("SELECT row_to_json(a)::text FROM asset a ORDER BY id"))
            .scalars()
            .all()
            == before
        )
        assert session.scalar(text("SELECT count(*) FROM processing_run")) == 0
        assert session.scalar(text("SELECT count(*) FROM retention_file")) == 0
        assert session.scalar(text("SELECT count(*) FROM job")) == 0


def test_読取取引をDB側で強制する(trial):
    engine, *_ = trial
    with read_session(engine) as session:
        assert session.scalar(text("SHOW transaction_read_only")) == "on"
        with pytest.raises(DBAPIError):
            session.execute(text("UPDATE asset SET collected_title='禁止'"))


@pytest.mark.parametrize(
    "reason",
    [
        "stop",
        "source-stop",
        "expired",
        "missing-retention",
        "rights",
        "sha",
        "subject",
        "people",
        "reference",
    ],
)
def test_選定前の期限権利人物参照不備を拒否する(trial, reason):
    engine, rows, _, now, source_id = trial
    with Session(engine) as session, session.begin():
        asset = session.get(Asset, UUID(rows[0]["asset_id"]))
        record = session.scalar(select(Retention).where(Retention.asset_id == asset.id))
        if reason == "stop":
            record.stopped_at = now
        elif reason == "source-stop":
            session.get(Source, source_id).policy = {"use_stopped": True}
        elif reason == "expired":
            record.expires_at = now
        elif reason == "missing-retention":
            session.delete(record)
        elif reason == "rights":
            asset.license_class = "analysis_only"
        elif reason == "sha":
            asset.sha256 = "0" * 64
        elif reason == "subject":
            asset.subject_id = None
        elif reason == "people":
            rows[0]["people"] = "uncertain"
        else:
            rows[0]["scene_ref"] = ""
    with pytest.raises((ValueError, PermissionError)):
        read_candidates(engine, rows, now=now)


def test_送信前回収後に停止変更と入力改変を再検査する(trial, tmp_path):
    engine, reviews, legacy, now, source_id = trial
    rows, pairs = read_candidates(engine, reviews, now=now)
    root = tmp_path / "private"
    prepare(select_candidates(rows, legacy, pairs, now=now), root, now=now)
    with Session(engine) as session, session.begin():
        session.get(Source, source_id).policy = {"deletion_requested": True}
    with pytest.raises(PermissionError):
        recheck(engine, root, now=now)


def test_OpenAIの既存許可は他providerへの送信許可にならない(trial, tmp_path):
    engine, reviews, legacy, now, source_id = trial
    with Session(engine) as session, session.begin():
        session.get(Source, source_id).policy = {
            "external_image_review": "openai-store-false",
            "external_image_review_allowed": True,
        }
    rows, pairs = read_candidates(engine, reviews, now=now)
    root = tmp_path / "private"
    manifest = prepare(select_candidates(rows, legacy, pairs, now=now), root, now=now)
    assert "external_authorized" not in manifest
    assert "external_image_review" not in manifest
    assert recheck(engine, root, now=now) <= now + timedelta(hours=24)


def test_実写真renderのCLIも回収後の利用停止を再検査する(trial, tmp_path, monkeypatch):
    from colorstats.trial_cli import main

    engine, reviews, legacy, now, source_id = trial
    rows, pairs = read_candidates(engine, reviews, now=now)
    root = tmp_path / "private"
    prepare(select_candidates(rows, legacy, pairs, now=now), root, now=now)
    with Session(engine) as session, session.begin():
        session.get(Source, source_id).policy = {"use_stopped": True}
    monkeypatch.setattr("colorstats.trial_cli.create_engine", lambda _: engine)
    monkeypatch.setenv("DATABASE_URL", "fixture")
    monkeypatch.setattr(
        "sys.argv",
        [
            "trial",
            "render",
            "--result-root",
            str(root),
            "--configurations",
            str(tmp_path / "none-config"),
            "--results",
            str(tmp_path / "none-results"),
            "--active-attempts",
            str(tmp_path / "none-attempts"),
        ],
    )
    with pytest.raises(PermissionError):
        main()
    assert not (root / "results.json").exists() and not (root / "pages").exists()
