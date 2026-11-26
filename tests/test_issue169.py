"""接続・新root・起動コマンドの安全境界を、本番へ接続せず検証する。"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from bench.issue114 import operate, statistics_operate
from bench.issue122 import runtime


@pytest.mark.parametrize("path", ["relative", *runtime.HISTORICAL,
                                 runtime.HISTORICAL[0] + "/attempt"])
def test_旧成果と相対rootを拒否する(path):
    with pytest.raises(ValueError):
        runtime.new_root(path)
    with pytest.raises(ValueError):
        runtime.remote_root(path)


def test_統計出力は同じ新rootと版だけで再開する(tmp_path):
    root, output = tmp_path / "run", tmp_path / "stats"
    runtime.prepare_output(root, output, "new-v2")
    marker = (output / "restart.json").read_bytes()
    runtime.prepare_output(root, output, "new-v2")
    assert (output / "restart.json").read_bytes() == marker
    with pytest.raises(FileExistsError):
        runtime.prepare_output(root, output, "different")
    old = tmp_path / "old"
    old.mkdir()
    (old / "snapshot.json").write_text("keep")
    with pytest.raises(FileExistsError):
        runtime.prepare_output(root, old, "new-v2")
    assert (old / "snapshot.json").read_text() == "keep"


def test_local_peerは秘密を探索せず実行権限を復元する(monkeypatch):
    pwd = pytest.importorskip("pwd")
    import psycopg
    import sqlalchemy

    monkeypatch.setattr(runtime.socket, "gethostname", lambda: "ubuntu-1")
    monkeypatch.setattr(runtime.os, "geteuid", lambda: 0)
    monkeypatch.setattr(pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=999))
    changed = []
    monkeypatch.setattr(runtime.os, "seteuid", changed.append)
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda url, **kwargs: kwargs["creator"])
    creator = runtime.database()
    calls = []

    def connect(**kwargs):
        calls.append(kwargs)
        raise OSError("接続失敗")

    monkeypatch.setattr(psycopg, "connect", connect)
    with pytest.raises(OSError):
        creator()
    assert changed == [999, 0]
    assert calls == [{"dbname": "colorstats", "host": "/var/run/postgresql"}]
    monkeypatch.setattr(runtime.socket, "gethostname", lambda: "retired-host")
    with pytest.raises(RuntimeError):
        runtime.database()


@pytest.mark.parametrize("action", ["smoke", "full", "audit-smoke", "audit-full"])
def test_実行コマンドは新rootと単独workerとlocal接続を使う(action):
    args = SimpleNamespace(action=action, root="/private/new", code="/code/fixed",
                           python="/venv/python", models="/models", name="new-v2")
    command = operate.command(args)
    assert "--root /private/new" in command and "--host ubuntu1" in command
    assert "ubuntu2" not in command and "ubuntu-2" not in command
    assert "launch.py" not in command and "DATABASE_URL" not in command
    assert ("--limit 3" in command) == (action in {"smoke", "audit-smoke"})


def test_比較統計の起動に新基準と出力先を明示する():
    args = SimpleNamespace(action="combined", root="/private/new", output="/private/stats",
                           code="/code", python="/python", name="v2", policy="terrain-v2",
                           baseline="/private/baseline", baseline_snapshot="fixed-hash",
                           old_only_output="/private/old-only")
    command = statistics_operate.command(args)
    assert "--baseline /private/baseline" in command
    assert "--output /private/stats" in command and "--policy terrain-v2" in command
    assert "--old-only-output /private/old-only" in command
    assert "ubuntu-2" not in command and "launch.py" not in command


def test_母集団seed合格条件と提示群を表示前に固定する(tmp_path):
    groups = {"terrain_required": [f"t{i}" for i in range(14)],
              "random_old": [f"o{i}" for i in range(50)],
              "random_new": [f"n{i}" for i in range(50)],
              "challenge": [f"c{i}" for i in range(10)]}
    value = {"population_sha256": "a" * 64, "seed": 169, "criteria": {"max_problems": 0},
             "groups": groups, "required_ids": [v for values in groups.values() for v in values]}
    path = tmp_path / "sampling.json"
    path.write_text(json.dumps(value))
    assert runtime.sampling(path) == value
    value["criteria"]["max_problems"] = 1
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        runtime.sampling(path)


def test_新計画は目視条件や提示結果の欠落を許可しない(tmp_path):
    with pytest.raises(PermissionError):
        runtime.human_reviews(None, tmp_path, {"version": runtime.VERSION})
    with pytest.raises(PermissionError):
        runtime.human_reviews(None, tmp_path, {"human_sampling": {"seed": 169}})


def test_配置先は現行hostだけである():
    source = (Path(__file__).resolve().parents[1] / "bench/issue122/deploy.py").read_text()
    assert '"ubuntu-2"' not in source


def test_固定manifestと単独partitionの差替えを拒否する(tmp_path):
    import hashlib

    path = tmp_path / "plan.json"
    plan = {"version": runtime.VERSION, "partitions": [runtime.PARTITION], "rows": [],
            "human_sampling": {"seed": 169}}
    path.write_text(json.dumps(plan))
    binding = tmp_path / "execution.json"
    binding.write_text(json.dumps({"plan_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}))
    assert runtime.read_plan(tmp_path) == plan
    path.write_text(json.dumps({**plan, "partitions": ["ubuntu1", "ubuntu2"]}))
    with pytest.raises(ValueError):
        runtime.read_plan(tmp_path)
    binding.write_text(json.dumps({"plan_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}))
    with pytest.raises(ValueError):
        runtime.read_plan(tmp_path)


def test_statusは実行したunitを問い合わせる():
    args = SimpleNamespace(action="status", root="/private/new", name="v2")
    command = operate.command(args)
    assert "colorstats-i114-v2-smoke" in command
    assert "colorstats-i114-v2-full" in command
    assert "-status" not in command and "systemd-run" not in command


@pytest.mark.parametrize("stale", [False, True])
def test_新しい旧基準は確認後の地形参照を要し建物を昇格しない(tmp_path, monkeypatch, stale):
    from contextlib import nullcontext

    from bench.issue114 import terrain_statistics as stats

    rows = [{"asset_id": str(i), "status": "building_not_aggregated"} for i in range(7607)]
    rows[200] = {"asset_id": "200", "status": "terrain_selected",
                 "privacy_review_run_id": "old" if stale else "confirmed"}
    old = {"taxonomy_version": "test", "assets": rows}
    (tmp_path / "selection.json").write_text(json.dumps(old))
    plan = {"version": runtime.VERSION, "partitions": [runtime.PARTITION],
            "human_sampling": {"seed": 169}}
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    import hashlib

    (tmp_path / "execution.json").write_text(json.dumps({
        "plan_sha256": hashlib.sha256((tmp_path / "plan.json").read_bytes()).hexdigest()}))
    monkeypatch.setattr(stats, "ROOT", tmp_path)
    monkeypatch.setattr(stats, "OLD", tmp_path)
    normalized = {**old, "assets": sorted(rows, key=lambda row: row["asset_id"])}
    monkeypatch.setattr(stats, "verify", lambda *a: {"selection_hash": stats.digest(normalized)})
    monkeypatch.setattr(stats, "human_holds", lambda: {
        "asset_ids": [str(i) for i in range(110)],
        "proof": {"human_runs_written": 0, "missing_references": 110}})
    monkeypatch.setattr(stats, "Session", lambda *a: nullcontext(None))
    monkeypatch.setattr(runtime, "human_reviews", lambda *a: {
        "150": "building-confirmed", "200": "confirmed"})
    if stale:
        with pytest.raises(ValueError, match="旧基準"):
            stats.selection(None, old_only=True)
    else:
        selected, evidence = stats.selection(None, old_only=True)
        assert selected["assets"][150]["status"] == "building_not_aggregated"
        assert selected["assets"][200]["privacy_review_run_id"] == "confirmed"
        assert selected["assets"][0]["status"] == "human_reference_pending"
        assert evidence["human_review"]["held_missing_new_reference"] == 110


@pytest.mark.parametrize("change", ["legacy", "missing_version", "missing_sampling",
                                    "empty_sampling"])
def test_旧形式への差替えで目視確認を迂回できない(tmp_path, change):
    import hashlib

    from bench.issue114 import terrain_statistics
    from bench.issue122 import statistics

    plan = {"version": runtime.VERSION, "partitions": [runtime.PARTITION], "rows": [],
            "human_sampling": {"seed": 169}}
    if change == "legacy":
        plan["version"] = "issue122-terrain-v1"
    elif change == "empty_sampling":
        plan["human_sampling"] = {}
    else:
        plan.pop("version" if change == "missing_version" else "human_sampling")
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    (tmp_path / "execution.json").write_text(json.dumps({
        "plan_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}))
    with pytest.raises(ValueError, match="現行manifest"):
        runtime.read_plan(tmp_path)
    for module in (statistics, terrain_statistics):
        from unittest.mock import patch

        with patch.object(module, "ROOT", tmp_path):
            if module is terrain_statistics:
                (tmp_path / "selection.json").write_text('{}')
                with patch.object(module, "OLD", tmp_path), pytest.raises(ValueError):
                    module.selection(None)
            else:
                with pytest.raises(ValueError):
                    module.selection(None)
    with pytest.raises(PermissionError):
        runtime.human_reviews(None, tmp_path, {})


def test_同じ対象集合でも旧のみの基準snapshotが違えば統計を開始しない(tmp_path, monkeypatch):
    import sys

    from bench.issue114 import terrain_statistics as stats
    from bench.issue122.production import save

    root, baseline, held, output = (tmp_path / name for name in
                                    ("restart", "baseline", "old-only", "output"))
    policy = "terrain-v2"
    selected = {"assets": [{"asset_id": "same", "privacy_review_run_id": "earlier-review"}]}
    save(held / "restart.json", {"root": str(root), "policy": policy, "version": runtime.VERSION})
    save(held / "selection.json", selected)
    save(baseline / "selection.json", {"assets": [
        {"asset_id": "same", "privacy_review_run_id": "current-review"}]})
    save(baseline / "summary.json", {"supported": 0, "roles": {}})
    save(held / "comparison.json", {
        "old_snapshot_id": "earlier-baseline", "new": {"snapshot_id": "held-snapshot"},
        "execution": {"diagnostic_old_only": True, "states": {"old/terrain_selected": 1}},
        "condition4": {"new": {}}})
    monkeypatch.setattr(stats, "verify", lambda *a: {"selection_hash": stats.digest(selected)})
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        save(output / "comparison.json", {"new": {}, "condition4": {"new": {}}})

    monkeypatch.setattr(stats.statistics, "main", generate)
    for name in ("ROOT", "OLD", "OLD_SNAPSHOT"):
        monkeypatch.setattr(stats, name, getattr(stats, name))
    for name in ("CODE", "ROOT", "OUTPUT", "POLICY", "OLD", "OLD_SNAPSHOT",
                 "database", "selection"):
        monkeypatch.setattr(stats.statistics, name, getattr(stats.statistics, name))
    monkeypatch.setattr(sys, "argv", ["terrain_statistics", "--root", str(root),
        "--baseline", str(baseline), "--baseline-snapshot", "current-baseline",
        "--old-only-output", str(held), "--output", str(output), "--policy", policy])
    with pytest.raises(ValueError, match="基準snapshot"):
        stats.main()
    assert calls == [] and not output.exists()
