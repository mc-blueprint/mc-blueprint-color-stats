import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Event, local
from uuid import UUID

import pytest

pytest.importorskip("pwd")

from bench.issue114 import media, output_directories, terrain_statistics
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

from colorstats import retention
from colorstats.queue import Queue as RealQueue
from colorstats.schema.models import Asset, RetentionFile
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue


@pytest.mark.parametrize("changed", [False, "same_count", "invalid_json"])
def test_保留一覧は同件数の差替えでも解析前に固定SHAで拒否する(tmp_path, monkeypatch, changed):
    directory = tmp_path / "human"
    directory.mkdir()
    path = directory / "holds-private.json"
    raw = json.dumps({"asset_ids": ["original"], "proof": {}}).encode()
    path.write_bytes(raw)
    monkeypatch.setattr(terrain_statistics, "ROOT", tmp_path)
    monkeypatch.setattr(terrain_statistics, "HUMAN_HOLDS_SHA256", hashlib.sha256(raw).hexdigest())
    if changed:
        path.write_bytes(b"{" if changed == "invalid_json" else
                         json.dumps({"asset_ids": ["replacement"], "proof": {}}).encode())
        with pytest.raises(ValueError, match="固定SHA"):
            terrain_statistics.human_holds()
    else:
        assert terrain_statistics.human_holds()["asset_ids"] == ["original"]


def test_出力先の逸脱は作成せずmkdirの置換も復元する(tmp_path, monkeypatch):
    monkeypatch.setattr(output_directories, "ROOT", tmp_path / "allowed")
    mkdir = os.mkdir
    outside = tmp_path / "outside"
    with pytest.raises(PermissionError, match="専用領域内"):
        with output_directories.anonymous_directories():
            outside.mkdir()
    assert not outside.exists()
    assert os.mkdir is mkdir


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("failure", [None, "lock", "stopped", "expired", "hash",
                                     "register", "commit"])
def test_旧媒体は全由来の利用確認後にリンクし失敗時は新規リンクだけ除去する(
        tmp_path, monkeypatch, existing, failure):
    source = tmp_path / "original"
    source.write_bytes(b"media")
    target = tmp_path / "mirror/media"
    target.parent.mkdir()
    if existing:
        os.link(source, target)
    events = []
    origins = [{"asset_id": str(UUID(int=i))} for i in (1, 2)]
    row = {"source": "/media", "sha256": "fixed", "origins": origins}

    def read(path):
        if path.name == "manifest.json":
            return {"files": [row]}
        return {"records": [], "bind_roots": []}

    @contextmanager
    def transaction():
        events.append("begin")
        yield object()
        events.append("commit")
        if failure == "commit":
            raise RuntimeError("commit")

    class Queue:
        def __init__(self, db, timeout):
            pass

        _transaction = staticmethod(transaction)

    @contextmanager
    def locked_queue(db):
        yield Queue(db, timeout=60)

    def lock(session):
        events.append("lock")
        if failure == "lock":
            raise RuntimeError("lock")

    def usable(session, asset_id, *, images):
        assert images
        events.append("usable")
        if len(events) == 4 and failure in ("stopped", "expired"):
            raise PermissionError(failure)

    link = os.link

    def create_link(old, new):
        assert events == ["begin", "lock", "usable", "usable"]
        events.append("link")
        link(source, new)

    def file_hash(path):
        if path == target:
            assert events[:4] == ["begin", "lock", "usable", "usable"]
            return "wrong" if failure == "hash" else "fixed"
        return "fixed"

    def register(session, asset_id, host, path, kind):
        assert target.exists()
        assert events[:4] == ["begin", "lock", "usable", "usable"]
        assert host == "ubuntu-2" and path == target and kind == "replica"
        events.append("register")
        if asset_id == UUID(int=2) and failure == "register":
            raise RuntimeError("register")

    saved = []
    monkeypatch.setattr(media, "locked_queue", locked_queue)
    monkeypatch.setattr(media, "_hash", file_hash)
    monkeypatch.setattr(media.os, "link", create_link)
    monkeypatch.setattr(media.retention, "lock", lock)
    monkeypatch.setattr(media.retention, "assert_usable", usable)
    monkeypatch.setattr(media.retention, "register_file", register)
    monkeypatch.setattr(media.media, "MIRROR", target.parent)
    monkeypatch.setattr(media.media, "MEDIA", tmp_path)
    monkeypatch.setattr(media.media, "read", read)
    monkeypatch.setattr(media.media, "save", lambda *args: saved.append(args))
    if failure:
        with pytest.raises((RuntimeError, PermissionError, AssertionError)):
            media.legacy(None)
        assert target.exists() is existing
        assert not saved
    else:
        media.legacy(None)
        assert target.stat().st_ino == source.stat().st_ino
        assert events.count("register") == 2
        assert events[-1] == "commit"
        assert saved[0][1]["files"] == 1
    assert source.read_bytes() == b"media"
    if existing:
        assert target.stat().st_ino == source.stat().st_ino


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="隔離PostgreSQL16専用")
@pytest.mark.parametrize("failure", ["register", "commit"])
def test_rollback後の新規リンク清掃が終わるまで別実行の保持登録を待たせる(
        queue, asset, tmp_path, monkeypatch, failure):
    source = tmp_path / "original"
    source.write_bytes(b"media")
    target = tmp_path / "mirror/media"
    with Session(queue.engine) as session, session.begin():
        retention.register_asset(session, session.get(Asset, asset), {}, "test")
    row = {"source": "/media", "sha256": "fixed", "origins": [{"asset_id": str(asset)}]}
    monkeypatch.setattr(media.media, "read", lambda p: {"files": [row]} if
                        p.name == "manifest.json" else {"records": []})
    monkeypatch.setattr(media.media, "MIRROR", target.parent)
    monkeypatch.setattr(media, "_hash", lambda p: "fixed")
    link = os.link
    monkeypatch.setattr(media.os, "link", lambda old, new: link(source, new))
    cleaning, attempted, allow_cleanup = Event(), Event(), Event()
    actor = local()
    register = retention.register_file
    unlink = Path.unlink
    acquired = []

    def fail_register(*args):
        register(*args)
        if getattr(actor, "first", False) and failure == "register":
            raise RuntimeError("register")

    def fail_commit(connection):
        if (getattr(actor, "first", False) and failure == "commit" and target.exists()
                and not getattr(actor, "failed", False)):
            actor.failed = True
            connection.connection.driver_connection.rollback()
            raise RuntimeError("commit")

    def cleanup(path, *args, **kwargs):
        if path == target:
            cleaning.set()
            assert allow_cleanup.wait(10)
        return unlink(path, *args, **kwargs)

    def first():
        actor.first = True
        media.legacy(queue.engine)

    def second():
        with RealQueue(queue.engine)._transaction() as session:
            acquired.append(session.scalar(text("SELECT pg_try_advisory_xact_lock(88, 1)")))
            attempted.set()
            retention.lock(session)
            if not target.exists():
                link(source, target)
            retention.register_file(session, asset, "ubuntu-2", target, "replica")

    monkeypatch.setattr(media.retention, "register_file", fail_register)
    monkeypatch.setattr(Path, "unlink", cleanup)
    event.listen(queue.engine, "commit", fail_commit)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            failed = pool.submit(first)
            try:
                assert cleaning.wait(10)
                competing = pool.submit(second)
                assert attempted.wait(10)
                assert acquired == [False]
                assert not competing.done()
            finally:
                allow_cleanup.set()
            with pytest.raises(RuntimeError, match=failure):
                failed.result(timeout=10)
            competing.result(timeout=10)
    finally:
        event.remove(queue.engine, "commit", fail_commit)
    assert target.stat().st_ino == source.stat().st_ino
    with Session(queue.engine) as session:
        registered = session.scalar(select(RetentionFile).where(
            RetentionFile.asset_id == asset, RetentionFile.host == "ubuntu-2",
            RetentionFile.path == str(target)))
        assert registered is not None and registered.deleted_at is None
        assert session.scalar(text("SELECT pg_try_advisory_xact_lock(88, 1)"))
