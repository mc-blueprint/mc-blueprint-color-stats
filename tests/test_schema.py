import io
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError

from colorstats.schema.models import (
    Asset,
    Base,
    ColorObservation,
    ProcessingRun,
    Region,
    Relation,
    Source,
)

ROOT = Path(__file__).resolve().parents[1]


def test_PostgreSQL用の適用と巻戻しSQLを接続なしで生成できる(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    output = io.StringIO()
    config = Config(str(ROOT / "alembic.ini"), output_buffer=output)
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    for table in Base.metadata.tables:
        assert f"CREATE TABLE {table}" in sql
    assert "JSONB" in sql
    assert "FOREIGN KEY(region_a, asset_id) REFERENCES region (id, asset_id)" in sql
    observation_sql = sql.split("CREATE TABLE color_observation (", 1)[1].split(";", 1)[0]
    assert "asset_id UUID," in observation_sql
    assert "region_id UUID," in observation_sql
    assert "CHECK ((asset_id IS NULL) <> (region_id IS NULL))" in observation_sql
    assert "FOREIGN KEY(asset_id) REFERENCES asset (id)" in observation_sql
    asset_sql = sql.split("CREATE TABLE asset (", 1)[1].split(";", 1)[0]
    for column in ("collected_title TEXT", "collected_location TEXT", "search_provider TEXT"):
        assert column in asset_sql
    assert "search_parameters JSONB" in asset_sql
    output.seek(0)
    output.truncate()
    command.downgrade(config, "0004:base", sql=True)
    sql = output.getvalue()
    for table in Base.metadata.tables:
        assert f"DROP TABLE {table}" in sql


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="CIのPostgreSQL専用")
def test_PostgreSQLで適用制約巻戻し再適用が成立する(monkeypatch):
    url = os.environ["TEST_DATABASE_URL"]
    engine = create_engine(url)
    assert engine.dialect.name == "postgresql"
    assert inspect(engine).get_table_names() == [], "空のテスト専用DBが必要です"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(ROOT / "alembic.ini"))
    try:
        command.upgrade(config, "head")
        with engine.begin() as connection:
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
            source_id, asset_id, other_asset_id, run_id = [uuid.uuid4() for _ in range(4)]
            connection.execute(
                Source.__table__.insert().values(
                    id=source_id,
                    url="https://example.test/source",
                    site="example.test",
                    license="CC0",
                    license_class="open",
                    retrieved_at=datetime.now(UTC),
                    policy={},
                )
            )
            for asset, provider in ((asset_id, "commons"), (other_asset_id, "openverse")):
                parameters = {
                    "endpoint": f"https://{provider}.example.test/search",
                    "api_version": "v1",
                    "sort": "relevance",
                    "filters": {"license": "CC0"},
                    "language": "ja",
                    "page_size": 20,
                    "rank_base": 1,
                    "page_base": 1,
                    "rank_scope": "page",
                }
                connection.execute(
                    Asset.__table__.insert().values(
                        id=asset,
                        source_id=source_id,
                        collected_title="城の正面",
                        collected_location="日本・長野県松本市",
                        url="https://example.test/image",
                        sha256="0" * 64,
                        width=10,
                        height=10,
                        storage_path="raw/00/test.png",
                        domain="real_building",
                        license_class="open",
                        search_provider=provider,
                        search_query="城",
                        search_parameters=parameters,
                        result_rank=3,
                        result_page=2,
                        retrieved_at=datetime.now(UTC),
                        taxonomy_version="0.1.0",
                        scene_attributes={},
                        quality={},
                    )
                )
                saved = connection.execute(select(Asset).where(Asset.id == asset)).mappings().one()
                assert saved["subject_id"] is None
                assert saved["collected_title"] == "城の正面"
                assert saved["collected_location"] == "日本・長野県松本市"
                assert saved["source_id"] == source_id
                assert saved["search_provider"] == provider
                assert saved["search_parameters"] == parameters
                assert (saved["search_query"], saved["result_rank"], saved["result_page"]) == (
                    "城",
                    3,
                    2,
                )
            connection.execute(
                ProcessingRun.__table__.insert().values(
                    id=run_id,
                    stage="color",
                    license_class="open",
                    config_hash="0" * 64,
                    parameters={},
                    code_version="test",
                    taxonomy_version="0.1.0",
                    node="ci",
                )
            )
            region_ids = [uuid.uuid4() for _ in range(3)]
            for region_id, asset in zip(
                region_ids, [asset_id, asset_id, other_asset_id], strict=True
            ):
                connection.execute(
                    Region.__table__.insert().values(
                        id=region_id,
                        asset_id=asset,
                        processing_run_id=run_id,
                        taxonomy_version="0.1.0",
                        label="wall_main",
                        bbox=[0, 0, 10, 10],
                        label_source="human",
                        confidence=1,
                        area_ratio=0.5,
                    )
                )
            relation = dict(
                asset_id=asset_id,
                region_a=region_ids[0],
                region_b=region_ids[1],
                processing_run_id=run_id,
                type="adjacent",
                delta_l=0.1,
                delta_c=0.2,
                delta_h=None,
                delta_e_ok=0.3,
                area_ratio=1,
            )
            connection.execute(Relation.__table__.insert().values(**relation))
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    Relation.__table__.insert().values(**(relation | {"region_b": region_ids[2]}))
                )
            observation = dict(
                asset_id=None,
                region_id=region_ids[0],
                processing_run_id=run_id,
                observed_oklab={"dominant": [0.5, 0, 0], "quantiles": []},
                material_oklab=None,
                material_confidence=None,
                area_ratio=0.5,
            )
            connection.execute(ColorObservation.__table__.insert().values(**observation))
            whole_image = observation | {"asset_id": asset_id, "region_id": None}
            whole_image_id = connection.execute(
                ColorObservation.__table__.insert()
                .values(**whole_image)
                .returning(ColorObservation.id)
            ).scalar_one()
            saved = connection.execute(
                select(ColorObservation).where(ColorObservation.id == whole_image_id)
            ).mappings().one()
            assert saved["asset_id"] == asset_id
            assert saved["region_id"] is None
            assert saved["observed_oklab"] == observation["observed_oklab"]
            assert saved["area_ratio"] == observation["area_ratio"]
            for changes in (
                {"area_ratio": 1.1},
                {"material_confidence": 0.8},
                {"region_id": uuid.uuid4()},
                {"region_id": None},
                {"asset_id": asset_id},
                {"asset_id": uuid.uuid4(), "region_id": None},
            ):
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(
                        ColorObservation.__table__.insert().values(**(observation | changes))
                    )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    Asset.__table__.update()
                    .where(Asset.id == asset_id)
                    .values(license_class="unknown")
                )
        command.downgrade(config, "base")
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT count(*) FROM alembic_version").scalar() == 0
        command.upgrade(config, "head")
        command.check(config)
    finally:
        command.downgrade(config, "base")
        engine.dispose()
