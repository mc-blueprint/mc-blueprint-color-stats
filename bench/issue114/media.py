"""#122の媒体コピー・SHA照合を#114専用領域へ適用する。"""

import argparse
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from bench.issue114.production import CODE, ROOT, database, output_identity
from bench.issue122 import media
from sqlalchemy import text

from colorstats import retention
from colorstats.analyze.segment import _hash
from colorstats.queue import Queue


@contextmanager
def locked_queue(db):
    """同じ保持lockを接続単位で持ち、取引のrollback後も清掃まで直列化する。"""
    with db.connect() as connection:
        try:
            with connection.begin():
                connection.execute(text("SET LOCAL statement_timeout = '60s'"))
                connection.execute(text("SELECT pg_advisory_lock(88, 1)"))
            yield Queue(connection, timeout=60)
        finally:
            try:
                connection.rollback()
                connection.execute(text("SELECT pg_advisory_unlock(88, 1)"))
                connection.commit()
            except BaseException:
                connection.invalidate()
                raise


def legacy(db):
    """旧訂正版の原画像・prepを新しい参照先へhardlinkし、元媒体は変更しない。"""
    old = Path("/mnt/data/derived/issue122-20261109/media-r3")
    raw = media.read(old / "raw/manifest.json")
    prep = media.read(old / "prep-complete.json")
    count = 0
    for kind, rows in (("raw", raw["files"]), ("prep", prep["records"])):
        for row in rows:
            source = old / "root" / Path(row["source"]).relative_to("/")
            target = media.MIRROR / Path(row["source"]).relative_to("/")
            origins = row["origins"] if kind == "raw" else [row]
            created = False
            with locked_queue(db) as queue:
                try:
                    with queue._transaction() as session:
                        retention.lock(session)
                        for origin in origins:
                            retention.assert_usable(session, origin["asset_id"], images=True)
                        assert _hash(source) == row["sha256"]
                        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                        if not target.exists():
                            os.link(source, target)
                            created = True
                        assert _hash(target) == row["sha256"]
                        for origin in origins:
                            retention.register_file(session, UUID(origin["asset_id"]), "ubuntu-2",
                                                    target, "replica")
                except BaseException:
                    if created:
                        target.unlink()
                    raise
            count += 1
    media.save(media.MEDIA / "legacy-complete.json", {
        "files": count, "raw_manifest_sha256": _hash(old / "raw/manifest.json"),
        "prep_manifest_sha256": _hash(old / "prep-complete.json"),
        "bind_roots": media.read(old / "verified.json")["bind_roots"]})
    print("legacy_media_verified files=" + str(count), flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("raw", "prep", "check", "legacy"))
    args = parser.parse_args()
    os.umask(0o077)
    output_identity()
    media.CODE, media.ROOT = CODE, ROOT
    media.MEDIA = ROOT / "media"
    media.MIRROR = media.MEDIA / "root"
    db = database()
    try:
        actions = {"raw": media.raw, "prep": media.prep, "check": media.check, "legacy": legacy}
        actions[args.action](db)
    finally:
        db.dispose()
