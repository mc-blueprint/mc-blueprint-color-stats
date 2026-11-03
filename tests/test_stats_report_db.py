import os

import pytest

from colorstats.stats.aggregate import aggregate
from colorstats.stats.report import report
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue
from tests.test_stats_aggregate import settings as settings
from tests.test_stats_snapshot_db import build, prepare

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="隔離PostgreSQL16専用",
)


def test_snapshot_db_contract_and_d15_denominators(queue, asset, tmp_path, settings):
    root = tmp_path / "snapshot"
    manifest = build(queue, prepare(queue, asset), root)
    stats = aggregate(root, manifest["snapshot_id"], settings)
    data = report(root, manifest["snapshot_id"], stats, settings)
    overall = data["overall"]
    assert overall["asset_rows"] == manifest["counts"]["assets"] == 9
    assert overall["sha_distinct"] == manifest["counts"]["sha_distinct"] == 7
    assert overall["duplicate_rows"] == 2
    assert overall["rights_eligible"]["numerator"] == manifest["counts"]["rights_eligible"] == 4
    assert overall["eligible"]["numerator"] == manifest["counts"]["representatives"] == 2
    assert overall["exclusions"]["sha_duplicate"]["numerator"] == 1
    assert overall["exclusions"]["restricted_weights"]["denominator"] == 9
    assert overall["exclusions"]["missing_analysis"]["numerator"] == 1
    assert overall["concentration"]["site"]["counts"] == {"fixture": 9}
    assert overall["concentration"]["author"]["counts"] == {"作者": 9}
    assert data["classification"]["image_unassigned"]["numerator"] == 9
    assert data["classification"]["unassigned"] == {
        "numerator": 2, "denominator": 2, "value": 1,
    }
    assert data["observation_exclusions"]["observations"]["eligible"]["numerator"] == 2
    assert not any(g["passed"] for g in data["usefulness_gates"].values())
