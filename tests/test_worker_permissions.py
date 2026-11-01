"""既存ロールへのmigration後の付与を、空のテストDBで検証する。"""

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from colorstats.analyze.prep import register
from colorstats.queue import Queue, RunInfo
from colorstats.schema.models import Asset, AssetDuplicate, Job, Source
from tests.test_prep_db import data

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="CIのPostgreSQL専用"
)
ROOT = Path(__file__).resolve().parents[1]


def test_既存ワーカーロールへ0004適用後の権限を付与しprepの重複登録が成功する(monkeypatch):
    url = os.environ["TEST_DATABASE_URL"]
    admin = create_engine(url)
    tables = set(inspect(admin).get_table_names())
    assert tables <= {"alembic_version"}, (
        "空のテスト専用DBが必要です"
    )
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(ROOT / "alembic.ini"))
    grants = (ROOT / "ops/deploy/worker_grants.sql").read_text(encoding="utf-8")
    worker = create_engine(url)

    @event.listens_for(worker, "connect")
    def set_role(connection, record):
        with connection.cursor() as cursor:
            cursor.execute("SET ROLE colorstats_worker")
        connection.commit()

    created = False
    try:
        command.upgrade(config, "0003")
        with admin.begin() as connection:
            existing = connection.execute(
                Job.__table__.insert().values(
                    stage="aggregate", stage_config_hash="b" * 64, payload={}
                ).returning(Job.id)
            ).scalar_one()
            connection.exec_driver_sql(
                "CREATE ROLE colorstats_worker NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
            )
            connection.exec_driver_sql(grants)
        created = True
        command.upgrade(config, "0004")
        with worker.connect() as connection, pytest.raises(DBAPIError) as error:
            connection.execute(select(AssetDuplicate))
        assert error.value.orig.sqlstate == "42501"
        command.upgrade(config, "head")
        with admin.begin() as connection:
            connection.exec_driver_sql(grants)
        with Session(worker) as session, session.begin():
            assert session.scalar(text("SELECT current_user")) == "colorstats_worker"
            assert not session.scalar(text(
                "SELECT rolsuper FROM pg_roles WHERE rolname=current_user"
            ))
            source = Source(url="https://example.test", site="test", license="CC0",
                            license_class="open", retrieved_at=datetime.now(UTC), policy={})
            session.add(source)
            session.flush()
            assets = [Asset(
                source_id=source.id, url="https://example.test/image", sha256="a" * 64,
                storage_path="raw/test.png", domain="real_building", license_class="open",
                retrieved_at=datetime.now(UTC), taxonomy_version="0.1.0",
                scene_attributes={}, quality={},
            ) for _ in range(2)]
            session.add_all(assets)
            session.flush()
            ids = [asset.id for asset in assets]
        queue = Queue(worker)
        claim = queue.claim(["aggregate"])
        assert claim.id == existing and claim.attempt == 1
        queue.complete(claim, RunInfo("open", "test", "0.1.0", "test", {}),
                       lambda session, run: None)
        for asset_id in ids:
            queue.enqueue("prep", asset_id, "a" * 64, {})
            claim = queue.claim(["prep"])
            queue.complete(claim, RunInfo("open", "test", "0.1.0", "test", {}),
                           lambda session, run, asset_id=asset_id: register(
                               session, run, data(asset_id)))
        with Session(worker) as session:
            pairs = session.scalars(select(AssetDuplicate)).all()
            assert len(pairs) == 1 and pairs[0].method == "sha256"
        with worker.begin() as connection, pytest.raises(DBAPIError) as error:
            connection.execute(text("UPDATE alembic_version SET version_num = '0003'"))
        assert error.value.orig.sqlstate == "42501"
    finally:
        worker.dispose()
        command.downgrade(config, "base")
        if created:
            with admin.begin() as connection:
                connection.exec_driver_sql("DROP OWNED BY colorstats_worker")
                connection.exec_driver_sql("DROP ROLE colorstats_worker")
        if "alembic_version" not in tables:
            with admin.begin() as connection:
                connection.exec_driver_sql("DROP TABLE alembic_version")
        admin.dispose()
