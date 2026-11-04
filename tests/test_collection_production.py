import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from colorstats.collect.targets import load_targets
from colorstats.schema.models import Job
from tests.test_collection_bias import DB
from tests.test_queue import database as database
from tests.test_queue import queue as queue

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "issue77_production", ROOT / "bench/issue77/production.py"
)
production = importlib.util.module_from_spec(spec)
spec.loader.exec_module(production)


def test_供給元の未測定とtimeoutを含む歩留まりを区別する():
    config = load_targets(ROOT / "bench/issue77/targets.yaml", ROOT / "taxonomy")
    result = {
        "strata": {
            "japanese-castle": {
                "counts": {"confirmed_subjects": 0},
                "history": [
                    {
                        "request": {"provider": "openverse"},
                        "state": "failed",
                        "counts": {"api_requests": 1, "timeouts": 1},
                    },
                    {
                        "request": {"provider": "openverse"},
                        "state": "committed",
                        "counts": {"api_requests": 2, "eligible_new_sha": 1},
                    },
                ],
            }
        }
    }
    summary = production.summarize(result, config)
    assert len(summary["strata_providers"]) == 24
    commons, openverse = summary["strata_providers"][:2]
    assert not commons["measured"] and commons["eligible_new_sha_per_api_request"] is None
    assert openverse["measured"]
    assert openverse["eligible_new_sha_per_api_request"] == pytest.approx(1 / 3)
    assert summary["totals"]["timeouts"] == 1


@DB
@pytest.mark.parametrize("residual", ["job", "run"])
def test_本番前の残存があれば収集を投入しない(queue, tmp_path, monkeypatch, residual):
    from colorstats.schema.models import ProcessingRun
    from tests.test_queue import INFO

    if residual == "job":
        queue.enqueue("collect", None, "a" * 64, {})
    else:
        with Session(queue.engine) as session, session.begin():
            session.add(
                ProcessingRun(
                    stage="collect",
                    config_hash="b" * 64,
                    license_class="open",
                    code_version=INFO.code_version,
                    taxonomy_version=INFO.taxonomy_version,
                    node="test",
                    parameters={"state": "running"},
                )
            )
    monkeypatch.setattr(production.bias, "plan", lambda *a, **kw: pytest.fail("収集は禁止"))
    with pytest.raises(ValueError, match="開始前"):
        production.execute(queue.engine, ROOT, tmp_path, "test")
    with Session(queue.engine) as session:
        assert len(session.scalars(select(Job)).all()) == (1 if residual == "job" else 0)
    assert (tmp_path / "before.json").exists()
