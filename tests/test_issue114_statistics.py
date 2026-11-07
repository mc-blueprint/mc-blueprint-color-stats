import json
import os

import pytest
from sqlalchemy import text

from tests.test_issue114_batch import analysis_report
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="隔離PostgreSQL専用",
)


def test_解析未完了は出力作成とDB接続の前に拒否する(tmp_path, monkeypatch):
    from bench.issue114 import statistics

    batch, output = tmp_path / "batch", tmp_path / "statistics"
    batch.mkdir()
    for name in ("ubuntu1", "ubuntu2"):
        (batch / name).mkdir()
        (batch / name / "report.json").write_text(json.dumps({
            "violations": [], "unclosed_attempts": 0,
            "completed_assets": 0, "pending_assets": 1,
        }))
        (batch / f"{name}-assets.json").write_text(json.dumps([name]))

    def no_database(*args, **kwargs):
        pytest.fail("解析未完了時にDBへ接続しました")

    monkeypatch.setattr(statistics, "engine", no_database)
    monkeypatch.setattr("sys.argv", ["statistics", "--batch", str(batch),
                                     "--output", str(output), "--code-version", "test"])
    with pytest.raises(ValueError, match="shade・color"):
        statistics.main()
    assert not output.exists()


def test_目視サンプル未確認では解析完了後も統計更新しない(tmp_path, monkeypatch):
    from bench.issue114 import statistics

    batch, output = tmp_path / "batch", tmp_path / "statistics"
    batch.mkdir()
    for name in ("ubuntu1", "ubuntu2"):
        (batch / name).mkdir()
        (batch / name / "report.json").write_text(json.dumps({
            "violations": [], "unclosed_attempts": 0, "completed_assets": 1, "pending_assets": 0,
            "jobs": analysis_report([name])["jobs"],
        }))
        (batch / f"{name}-assets.json").write_text(json.dumps([name]))
    monkeypatch.setattr("sys.argv", ["statistics", "--batch", str(batch),
                                     "--output", str(output), "--code-version", "test"])
    with pytest.raises(ValueError, match="目視サンプル"):
        statistics.main()
    assert not output.exists()


def test_採用分だけの統計selectionへ全量prepから必要分だけを取り込む(
    queue, asset, tmp_path, monkeypatch,
):
    from uuid import uuid4

    from bench.issue114 import statistics
    from bench.issue114.privacy import digest, review_state, save

    batch, output, old = tmp_path / "batch", tmp_path / "statistics", tmp_path / "old"
    batch.mkdir()
    old.mkdir()
    aid, other, prep = str(asset), str(uuid4()), str(uuid4())
    save(old / "selection.json", {"assets": []})
    save(batch / "new-assets.json", [aid])
    save(batch / "prep-report.json", [
        {"asset_id": other, "status": "succeeded", "run_id": str(uuid4())},
        {"asset_id": aid, "status": "succeeded", "run_id": prep},
    ])
    save(batch / "privacy-decisions.json", [{"asset_id": aid}, {"asset_id": other}])
    save(batch / "privacy-validation.json", {
        "approved": True, "decisions_sha256": digest(batch / "privacy-decisions.json"),
        "review_state_sha256": review_state(queue.engine, [aid, other]),
    })
    for name, ids in (("ubuntu1", [aid]), ("ubuntu2", [])):
        (batch / name).mkdir()
        save(batch / f"{name}-assets.json", ids)
        save(batch / name / "report.json", analysis_report(ids))

    def snapshot_boundary(db, selection, *args, **kwargs):
        assert selection["assets"] == [{"asset_id": aid, "prep_run_id": prep,
                                         "segment_run_id": "run", "color_run_id": "run"}]
        raise RuntimeError("snapshot境界まで確認")

    monkeypatch.setattr(statistics, "engine", lambda _: queue.engine)
    monkeypatch.setattr(statistics, "OLD", old)
    monkeypatch.setattr(statistics, "preserved", lambda *args: {})
    monkeypatch.setattr(statistics, "execute", snapshot_boundary)
    monkeypatch.setattr("sys.argv", ["statistics", "--batch", str(batch),
                                     "--output", str(output), "--code-version", "test"])
    with pytest.raises(RuntimeError, match="snapshot境界"):
        statistics.main()


def test_旧assetとrunの行hashを照合し変更を検出する(queue, asset, tmp_path):
    from bench.issue114.statistics import preserved

    with queue.engine.connect() as connection:
        for name, table in (("assets", "asset"), ("runs", "processing_run")):
            values = dict(connection.execute(text(
                f"SELECT id::text,md5(row_to_json(t)::text) FROM {table} t ORDER BY id"
            )).all())
            (tmp_path / f"baseline-{name}.json").write_text(json.dumps(values))
    assert preserved(queue.engine, tmp_path)["assets"] == {"before": 1, "changed": []}
    with queue.engine.begin() as connection:
        connection.execute(
            text("UPDATE asset SET collected_title='変更検出のfixture' WHERE id=:id"),
            {"id": asset},
        )
    with pytest.raises(ValueError, match="旧assets"):
        preserved(queue.engine, tmp_path)
