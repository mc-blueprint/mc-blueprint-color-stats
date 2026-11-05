import os
from copy import deepcopy
from pathlib import Path
from uuid import UUID

import pytest
import yaml
from sqlalchemy.orm import Session

from colorstats.pack_boundary import validate_public
from colorstats.schema.models import Asset, Source
from colorstats.stats.reassess import execute
from colorstats.stats.snapshot import verify
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue
from tests.test_retention import PUBLIC
from tests.test_stats_snapshot_db import build, prepare

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="隔離PostgreSQL16専用",
)


def test_READ_ONLY計画と単一取引の冪等追記と配布拒否(queue, asset):
    policies = yaml.safe_load(Path("configs/source_policy.yaml").read_text(encoding="utf-8"))[
        "sources"
    ]
    with Session(queue.engine) as session, session.begin():
        row = session.get(Asset, asset)
        source = session.get(Source, row.source_id)
        source.site = row.search_provider = "wikimedia_commons"
        source.license = "cc-by-sa-4.0"
        row.quality = {"license": source.license, "metadata": {"raw": "元meta"}}
        original = deepcopy(row.quality)
        provenance = (source.url, source.license, source.author, source.retrieved_at)
    first = execute(queue.engine, [asset], policies)
    assert first["before"] == {"open": 1}
    assert first["after"] == {"analysis_only": 1}
    assert first["changes"] == 1
    with Session(queue.engine) as session:
        assert session.get(Asset, asset).quality == original
    with pytest.raises(ValueError, match="計画"):
        execute(queue.engine, [asset], policies, apply=True, expected_hash="wrong")
    applied = execute(queue.engine, [asset], policies, apply=True, expected_hash=first["plan_hash"])
    assert applied["plan_hash"] == first["plan_hash"]
    repeated = execute(
        queue.engine, [asset], policies, apply=True, expected_hash=first["plan_hash"],
    )
    assert repeated["changes"] == 0
    with Session(queue.engine) as session, session.begin():
        row = session.get(Asset, asset)
        source = session.get(Source, row.source_id)
        assert (source.url, source.license, source.author, source.retrieved_at) == provenance
        assert all(row.quality[key] == value for key, value in original.items())
        assert "retention_until" not in row.quality
        selection = {"assets": [{"asset_id": str(asset)}]}
        validate_public(PUBLIC, session=session, selection=selection)
        for key, value in (("image", b"image"), ("meta", row.quality), ("source", source.url)):
            with pytest.raises(ValueError, match="allowlist"):
                validate_public(PUBLIC | {key: value}, session=session, selection=selection)


def test_再評価後のsnapshotだけがSAを採用し旧版hashを保持する(queue, asset, tmp_path):
    selection = prepare(queue, asset)
    policies = yaml.safe_load(Path("configs/source_policy.yaml").read_text(encoding="utf-8"))[
        "sources"
    ]
    with Session(queue.engine) as session, session.begin():
        row = session.get(Asset, UUID(int=3))
        source = session.get(Source, row.source_id)
        source.site = row.search_provider = "wikimedia_commons"
        row.sha256 = "3" * 64
    old = build(queue, selection, tmp_path / "old")
    ids = [UUID(item["asset_id"]) for item in selection["assets"]]
    dry = execute(queue.engine, ids, policies)
    assert dry["changes"] == 1
    assert dry["exclusions"]["noncommercial"] == 1
    execute(queue.engine, ids, policies, apply=True, expected_hash=dry["plan_hash"])
    new = build(queue, selection, tmp_path / "new")
    assert new["counts"]["rights_eligible"] == old["counts"]["rights_eligible"] + 1
    assert new["counts"]["representatives"] == old["counts"]["representatives"] + 1
    assert verify(tmp_path / "old", old["snapshot_id"]) == old
