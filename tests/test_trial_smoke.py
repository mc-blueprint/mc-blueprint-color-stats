"""構成ごとのsmoke証明を、合成backendだけで反証する。"""

import copy
import socket
from datetime import UTC, datetime, timedelta

import pytest

from colorstats.trial_cli import synthetic_inputs
from colorstats.trial_fake import FakeRunPod, synthetic_plan
from colorstats.trial_inputs import sha
from colorstats.trial_ledger import Budget
from colorstats.trial_runner import Runner
from colorstats.trial_smoke import settings_signature, verify_smokes


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("外部通信を禁止しています")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    root = tmp_path / "smoke"
    synthetic_inputs(root)
    plan = synthetic_plan(root, purpose="smoke")
    for field in ("configurations", "deployments"):
        plan[field] = {k: v for k, v in plan[field].items() if k in "AE"}
    with Budget(plan["budget_ledger"], 15) as budget:
        runner = Runner(plan, FakeRunPod(plan["region"]), fake=True, budget=budget)
        for _ in range(100):
            if runner.tick() == "complete":
                break
        assert runner.state["status"] == "complete"
        assert sum(r["status"] == "success" for r in runner.state["results"]) == 6
        # 合成backendの記録で、実GPU証拠の形式検査だけを検証する。
        runner.state["synthetic"] = False
        budget.data["runs"][runner.state["run_id"]]["synthetic"] = False
        runner.save("test_evidence")
        checkpoint = root / f"execution/{runner.sequence - 1:06}.json"
        plan["smoke_records"] = dict.fromkeys(
            "AE", {"file": str(checkpoint), "sha256": sha(checkpoint.read_bytes())}
        )
        yield plan, budget, runner, checkpoint


def test_AE各3成功と削除と同じ台帳を構成別に検証し元記録を変更しない(evidence):
    plan, budget, _, path = evidence
    before = path.read_bytes(), budget.path.read_bytes()
    verify_smokes(plan, budget, now=datetime.now(UTC))
    assert (path.read_bytes(), budget.path.read_bytes()) == before
    assert budget.prior_usd("main") >= 0


@pytest.mark.parametrize("key", ["A", "E"])
@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "failed",
        "empty",
        "attempt",
        "not_deleted",
        "resource",
        "result_sha",
        "manifest_sha",
        "settings",
        "fake",
        "incomplete",
        "ledger",
        "reference_sha",
    ],
)
def test_欠測失敗別設定や削除と台帳の不一致を本番へ通さない(evidence, key, change):
    plan, budget, runner, path = evidence
    state = runner.state
    row = next(r for r in state["results"] if r["configuration_id"] == key)
    resource = next(r for r in state["resources"] if r["configuration_id"] == key)
    if change in {"missing", "failed"}:
        row["status"] = change
    elif change == "empty":
        row["regions"] = []
    elif change == "attempt":
        row["attempt"] = "old"
    elif change == "not_deleted":
        resource["confirmed_deleted"] = False
    elif change == "resource":
        resource["id"] = "other"
    elif change in {"result_sha", "manifest_sha"}:
        state["results_sha256" if change == "result_sha" else "manifest_sha256"] = "0" * 64
    elif change == "settings":
        plan["deployments"][key]["image_timeout_seconds"] -= 1
    elif change == "fake":
        state["synthetic"] = True
        budget.data["runs"][state["run_id"]]["synthetic"] = True
    elif change == "incomplete":
        state["status"] = "stopped"
    elif change == "ledger":
        budget.data["runs"].clear()
    elif change == "reference_sha":
        plan["smoke_records"][key] = {"file": str(path), "sha256": "0" * 64}
    if change not in {"settings", "ledger", "reference_sha", "resource"}:
        runner.save("test_invalid_evidence")
        path = runner.root / f"execution/{runner.sequence - 1:06}.json"
        plan["smoke_records"] = dict.fromkeys(
            "AE", {"file": str(path), "sha256": sha(path.read_bytes())}
        )
    elif change == "resource":
        # USD台帳側だけが異なる資源を参照する場合。
        budget.data["runs"][state["run_id"]]["resources"][0]["id"] = "other"
    with pytest.raises((PermissionError, ValueError)):
        verify_smokes(plan, budget, now=datetime.now(UTC))


def test_未選択構成は証明を要求せず選択構成の省略は拒否する(evidence):
    plan, budget, _, _ = evidence
    plan["smoke_records"].pop("E")
    with pytest.raises(ValueError, match="選択構成"):
        verify_smokes(plan, budget, now=datetime.now(UTC))


def test_本番とsmokeのPodは別資源で費用を引き継ぐ(evidence, tmp_path):
    plan, budget, smoke, _ = evidence
    main_root = tmp_path / "main"
    synthetic_inputs(main_root)
    main_plan = copy.deepcopy(plan)
    main_plan.update(result_root=str(main_root), purpose="trial")
    backend = FakeRunPod(plan["region"])
    # 実行は合成だけ。smoke証明の検証は上のテストで独立して行う。
    smoke.state["synthetic"] = True
    budget.data["runs"][smoke.state["run_id"]]["synthetic"] = True
    runner = Runner(main_plan, backend, fake=True, budget=budget)
    assert runner.reserve("A") <= 3.20
    assert runner.reserve("E") <= 2.50
    for _ in range(250):
        if runner.tick() == "complete":
            break
    assert runner.state["status"] == "complete"
    assert len(runner.state["results"]) == 60
    assert {r["configuration_id"] for r in runner.state["resources"]} == set("AE")
    assert not (
        {r["name"] for r in smoke.state["resources"]}
        & {r["name"] for r in runner.state["resources"]}
    )
    assert all(r["confirmed_deleted"] for r in runner.state["resources"])
    assert budget.cap == 15


def test_他構成の設定変更は構成単位の証明を変えない(evidence):
    plan, _, _, _ = evidence
    prior = settings_signature(plan, "A")
    prior_e = settings_signature(plan, "E")
    plan["deployments"]["E"]["gpu"] = "other"
    assert settings_signature(plan, "A") == prior
    assert settings_signature(plan, "E") != prior_e


def test_全選択構成に同じ単一checkpointを指定できる(evidence):
    plan, budget, _, _ = evidence
    plan["smoke_record"] = plan.pop("smoke_records")["A"]
    verify_smokes(plan, budget, now=datetime.now(UTC))


def test_期限切れの元smoke結果を流用しない(evidence):
    plan, budget, _, _ = evidence
    with pytest.raises(PermissionError, match="期限"):
        verify_smokes(plan, budget, now=datetime.now(UTC) + timedelta(days=4))


def test_他構成の設定が異なる別runから各構成の証明を選べる(evidence, tmp_path):
    plan, budget, first, _ = evidence
    root = tmp_path / "second-smoke"
    synthetic_inputs(root)
    second_plan = copy.deepcopy(plan)
    second_plan["result_root"] = str(root)
    second_plan["deployments"]["A"]["memory_fraction"] = 0.80
    budget.data["runs"][first.state["run_id"]]["synthetic"] = True
    second = Runner(second_plan, FakeRunPod(plan["region"]), fake=True, budget=budget)
    for _ in range(100):
        if second.tick() == "complete":
            break
    assert second.state["status"] == "complete"
    for run in budget.data["runs"].values():
        run["synthetic"] = False
    second.state["synthetic"] = False
    second.save("test_second_evidence")
    path = root / f"execution/{second.sequence - 1:06}.json"
    plan["smoke_records"] = {
        "A": plan["smoke_records"]["A"],
        "E": {"file": str(path), "sha256": sha(path.read_bytes())},
    }
    verify_smokes(plan, budget, now=datetime.now(UTC))
    plan["smoke_records"]["A"] = plan["smoke_records"]["E"]
    with pytest.raises(PermissionError, match="同じ構成"):
        verify_smokes(plan, budget, now=datetime.now(UTC))
