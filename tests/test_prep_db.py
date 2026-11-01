import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from colorstats.analyze.prep import register
from colorstats.schema.models import Asset, AssetDuplicate, Subject, SubjectCandidate
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="CIのPostgreSQL専用"
)


def data(asset_id, sha="a", phash="0000000000000000"):
    return {
        "asset_id": str(asset_id), "sha256": sha * 64, "phash": phash,
        "width": 400, "height": 300, "sharpness": 200,
        "watermark_suspected": False, "collage_suspected": False,
        "colors": 20, "luminance": 100,
    }


def add_asset(session, original, **changes):
    values = {
        column.name: getattr(original, column.name)
        for column in Asset.__table__.columns if column.name != "id"
    }
    result = Asset(**(values | changes))
    session.add(result)
    session.flush()
    return result


def subject(session, name):
    result = Subject(
        name=name, domain="real_building", taxonomy_version="0.1.0", scene_attributes={}
    )
    session.add(result)
    session.flush()
    return result.id


def test_unidentified_duplicates_remain_null_without_creating_subjects(queue, asset):
    with Session(queue.engine) as session, session.begin():
        original = session.get(Asset, asset)
        original.quality = {"author": "収集時の作者"}
        count = session.scalar(select(func.count()).select_from(Subject))
        register(session, None, data(asset))
        session.flush()
        assert original.subject_id is None
        assert session.scalar(select(func.count()).select_from(AssetDuplicate)) == 0
        second = add_asset(session, original)
        third = add_asset(session, original, sha256="b" * 64)
        for item, sha in ((original, "a"), (second, "a"), (third, "b")):
            register(session, None, data(item.id, sha))
        session.flush()
        assert all(item.subject_id is None for item in (original, second, third))
        assert original.quality["author"] == "収集時の作者"
        assert session.scalar(select(func.count()).select_from(Subject)) == count
        assert session.scalar(select(func.count()).select_from(SubjectCandidate)) == 0
        pairs = session.scalars(select(AssetDuplicate)).all()
        assert len(pairs) == 3
        assert sorted(pair.method for pair in pairs) == ["phash", "phash", "sha256"]


@pytest.mark.parametrize("method", ["none", "sha256", "phash"])
def test_confirmed_subject_is_preserved_and_near_match_is_only_candidate(queue, asset, method):
    with Session(queue.engine) as session, session.begin():
        original = session.get(Asset, asset)
        original.subject_id = subject(session, "確定建築")
        confirmed = original.subject_id
        other_subject = subject(session, "別の確定建築")
        other = add_asset(
            session, original, subject_id=other_subject,
            sha256=("a" if method == "sha256" else "b") * 64,
            phash=None if method == "none" else "0000000000000001",
        )
        register(session, None, data(asset))
        session.flush()
        assert original.subject_id == confirmed
        assert other.subject_id == other_subject
        if method != "none":
            assert session.get(SubjectCandidate, (asset, other_subject)) is not None
            assert session.get(SubjectCandidate, (other.id, confirmed)) is not None


@pytest.mark.parametrize("reverse", [False, True])
def test_exact_match_inherits_unique_subject_in_both_processing_orders(queue, asset, reverse):
    with Session(queue.engine) as session, session.begin():
        original = session.get(Asset, asset)
        original.subject_id = subject(session, "確定建築")
        unknown = add_asset(session, original, subject_id=None)
        near = add_asset(session, original, subject_id=None, sha256="b" * 64,
                         phash="0000000000000001")
        register(session, None, data(asset if reverse else unknown.id))
        session.flush()
        assert unknown.subject_id == original.subject_id
        assert near.subject_id is None
        assert session.get(SubjectCandidate, (near.id, original.subject_id)) is not None


def test_conflicting_exact_subjects_leave_unknown_unidentified(queue, asset):
    with Session(queue.engine) as session, session.begin():
        original = session.get(Asset, asset)
        original.subject_id = subject(session, "建築A")
        second = add_asset(session, original, subject_id=subject(session, "建築B"))
        unknown = add_asset(session, original, subject_id=None)
        register(session, None, data(unknown.id))
        session.flush()
        assert unknown.subject_id is None
        for item in (original, second):
            assert session.get(SubjectCandidate, (unknown.id, item.subject_id)) is not None


@pytest.mark.parametrize("confirmed", [False, True])
def test_parallel_registration_and_retry_keep_one_duplicate_graph(queue, asset, confirmed):
    with Session(queue.engine) as session, session.begin():
        original = session.get(Asset, asset)
        original.subject_id = subject(session, "確定建築") if confirmed else None
        expected = original.subject_id
        second = add_asset(session, original, subject_id=None)
        third = add_asset(session, original, subject_id=None, sha256="b" * 64)
        ids = [asset, second.id, third.id]
    barrier = Barrier(3)

    def process(index):
        with Session(queue.engine) as session, session.begin():
            # ロック待ちの前に読み込んだ値も、登録時に最新状態へ読み直す。
            session.get(Asset, ids[index])
            barrier.wait(timeout=10)
            register(session, None, data(ids[index], "b" if index == 2 else "a"))

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(process, range(3)))
    with Session(queue.engine) as session, session.begin():
        assert [session.get(Asset, item).subject_id for item in ids] == [expected, expected, None]
        assert session.scalar(select(func.count()).select_from(AssetDuplicate)) == 3
        for index in range(3):
            register(session, None, data(ids[index], "b" if index == 2 else "a"))
        session.flush()
        assert [session.get(Asset, item).subject_id for item in ids] == [expected, expected, None]
        pairs = session.scalars(select(AssetDuplicate)).all()
        assert len(pairs) == 3
        assert all(pair.asset_a < pair.asset_b for pair in pairs)
        assert sorted(pair.method for pair in pairs) == ["phash", "phash", "sha256"]


def test_exact_evidence_replaces_equal_confidence_phash_evidence(queue, asset):
    with Session(queue.engine) as session, session.begin():
        original = session.get(Asset, asset)
        original.subject_id = subject(session, "確定建築")
        unknown = add_asset(session, original, subject_id=None, sha256="b" * 64,
                            phash="0000000000000000")
        register(session, None, data(asset))
        session.flush()
        candidate = session.get(SubjectCandidate, (unknown.id, original.subject_id))
        assert candidate.evidence["method"] == "phash"
        assert unknown.subject_id is None
        register(session, None, data(unknown.id))
        session.flush()
        assert unknown.subject_id == original.subject_id
        session.refresh(candidate)
        assert candidate.evidence["method"] == "sha256"
