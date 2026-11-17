"""クラウド接続を遮断した状態遷移・予算・再開の回帰検証。"""

import copy
import json
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from colorstats.api_budget import digest
from colorstats.trial_cli import synthetic_inputs
from colorstats.trial_costs import RESERVATIONS, cost, select_candidate, summary, time_limit
from colorstats.trial_fake import FakeRunPod, synthetic_plan
from colorstats.trial_inputs import sha
from colorstats.trial_ledger import Budget
from colorstats.trial_results import read_results
from colorstats.trial_runner import Runner, validate_plan, writer
from colorstats.trial_runpod import ProviderUnavailable


class Clock:
    def __init__(self):
        self.seconds = 0
        self.start = datetime.now(UTC)

    def now(self):
        return self.start + timedelta(seconds=self.seconds)


@pytest.fixture
def trial(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("外部通信を禁止しています")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    root = tmp_path / "trial"
    synthetic_inputs(root)
    clock = Clock()
    plan = synthetic_plan(root)
    backend = FakeRunPod(plan["region"])
    return root, plan, backend, clock


def runner_for(trial, **kwargs):
    _, plan, backend, clock = trial
    return Runner(
        plan, backend, clock=clock.now, monotonic=lambda: clock.seconds, fake=True, **kwargs
    )


def drive(runner, maximum=500):
    for _ in range(maximum):
        status = runner.tick()
        if status in {"complete", "stopped"}:
            return status
    raise AssertionError("状態遷移が完了しません")


@pytest.mark.parametrize("concurrency", [1, 2])
def test_合成30件を起動回収150結果受領比較削除費用記録まで通す(trial, concurrency):
    root, plan, backend, _ = trial
    plan["concurrency"] = concurrency
    with writer(root):
        runner = runner_for(trial)
        assert drive(runner) == "complete"
    assert len(read_results(root)[2]) == 150
    assert len(runner.state["resources"]) == 5
    assert all(r["status"] == "closed" for r in runner.state["resources"])
    assert not backend.pods and not backend.jobs
    assert len(backend.deleted) == 5
    assert backend.events.count("submit") == 150
    assert backend.events.count("remove_image") == 150
    assert len(json.loads((root / "number-map.json").read_text())["rows"]) == 30
    assert all(r["billed_usd"] == 0 for r in runner.state["cost_summary"])
    assert all(r["nonempty_success_count"] == 30 for r in summary(runner.state))


def test_実接続扱いは送信課金許可なしでは起動前に止まる(trial):
    _, plan, backend, clock = trial
    backend.synthetic = False
    with Budget(Path(plan["budget_ledger"]), 15) as budget:
        runner = Runner(plan, backend, clock=clock.now, budget=budget)
        assert drive(runner) == "stopped"
    assert backend.events == []


def test_ライセンス未確認なら合成GPU_smokeも拒否する(trial, request):
    root, plan, backend, clock = trial
    plan["purpose"] = "smoke"
    backend.synthetic = False
    budget = Budget(Path(plan["budget_ledger"]), 15)
    budget.__enter__()
    request.addfinalizer(lambda: budget.__exit__())
    runner = Runner(plan, backend, clock=clock.now, budget=budget)
    runner.authorization = {
        "plan_sha256": digest(plan),
        "manifest_sha256": sha((root / "manifest.json").read_bytes()),
        "provider": "runpod",
        "region": plan["region"],
        "product": "secure-on-demand",
        "send_images": True,
        "billing": True,
        "delete_new_resources": True,
        "retention_confirmed": True,
        "user_text": "合成smokeのみ許可",
        "authorized_at": clock.now().isoformat(),
        "operations": {
            "region": plan["region"],
            "checked_at": clock.now().isoformat(),
            **dict.fromkeys(
                ["status_ref", "maintenance_ref", "capacity_ref", "data_terms_ref"], "a" * 64
            ),
        },
        "expires_at": (clock.now() + timedelta(hours=1)).isoformat(),
        "max_usd": 15,
    }
    with pytest.raises(PermissionError, match="ライセンス"):
        runner.authorize()
    assert backend.events == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("container", "mutable:latest"),
        ("image_timeout_seconds", 121),
        ("gpu_count", 3),
        ("usd_hour", 0),
        ("fixed_usd", 2),
    ],
)
def test_固定値や予約に不一致があれば起動前に拒否する(trial, field, value):
    _, plan, backend, _ = trial
    plan["deployments"]["A"][field] = value
    with pytest.raises((ValueError, KeyError)):
        runner_for(trial)
    assert backend.events == []


def test_同時writerを拒否し解放後に再取得できる(trial):
    root, *_ = trial
    with writer(root):
        with pytest.raises(RuntimeError, match="別writer"), writer(root):
            pass
    with writer(root):
        pass


def test_保存した実行状態から回収途中を再開できる(trial):
    runner = runner_for(trial)
    for _ in range(10):
        runner.tick()
    count = len(runner.state["results"])
    replacement = runner_for(trial)
    assert len(replacement.state["results"]) == count
    assert drive(replacement) == "complete"
    assert len(replacement.state["resources"]) == 5


@pytest.mark.parametrize("kind", ["config", "gpu", "manifest", "checkpoint"])
def test_再開時の固定参照変更を拒否する(trial, kind):
    root, plan, _, _ = trial
    runner = runner_for(trial)
    runner.tick()
    if kind == "config":
        plan["configurations"]["A"]["code_sha256"] = "0" * 64
    elif kind == "gpu":
        plan["deployments"]["A"]["gpu"] = "other"
    elif kind == "manifest":
        path = root / "manifest.json"
        path.write_text(path.read_text() + " ")
    else:
        path = root / "execution/000000.json"
        path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError):
        runner_for(trial)


def until_sent(runner):
    for _ in range(8):
        runner.tick()
        if runner.state["resources"] and runner.state["resources"][-1]["current"]:
            return runner.state["resources"][-1]
    raise AssertionError("入力送信へ進みません")


@pytest.mark.parametrize("field", ["attempt", "input_sha256", "configuration_sha256", "trial_id"])
def test_旧attemptや参照差を受領確定へ混ぜない(trial, field):
    runner = runner_for(trial)
    resource = until_sent(runner)
    backend = trial[2]
    value, _ = backend.jobs[(resource["attempt"], resource["current"]["trial_id"])]
    value[field] = "old"
    assert drive(runner) == "stopped"
    assert runner.state["results"] == []
    assert not (trial[0] / "results.json").exists()
    assert not backend.pods


def test_未回収2分で次の入力を止め新設資源を終了する(trial):
    runner = runner_for(trial)
    until_sent(runner)
    trial[2].jobs.clear()
    trial[3].seconds += 121
    assert drive(runner) == "stopped"
    assert runner.state["stop_reason"] == "unrecovered"
    assert trial[2].events.count("submit") == 1
    assert not trial[2].pods


def test_権利期限失効後も新設資源の削除処理へ進む(trial):
    runner = runner_for(trial)
    until_sent(runner)
    trial[3].seconds += 4 * 86400
    assert drive(runner) == "stopped"
    assert not trial[2].pods


def test_価格変更を保存して停止し過去単価で過小計上しない(trial):
    runner = runner_for(trial)
    runner.tick()
    pod = next(iter(trial[2].pods.values()))
    pod["cost"] = 3
    assert drive(runner) == "stopped"
    resource = runner.state["resources"][0]
    assert resource["observed_usd_hour"] == 3
    assert resource["estimated_usd"] >= 3 / 3600


def test_時間上限に終了余裕を残して停止する(trial):
    runner = runner_for(trial)
    runner.tick()
    trial[3].seconds += 3600
    assert drive(runner) == "stopped"
    assert runner.state["stop_reason"] == "time_limit"


def test_残予約不足では次の構成を起動しない(trial):
    runner = runner_for(trial)
    runner.state["measurement_usd"] = 13
    assert drive(runner) == "stopped"
    assert trial[2].events == []


def test_管理API不通で二重起動せず未確認を保全する(trial, monkeypatch):
    runner = runner_for(trial)
    runner.tick()

    def unavailable(*args):
        raise ProviderUnavailable("確認できない")

    monkeypatch.setattr(trial[2], "status", unavailable)
    monkeypatch.setattr(trial[2], "close", unavailable)
    runner.tick()
    runner.tick()
    runner.tick()
    assert len(runner.state["resources"]) == 1
    assert trial[2].events.count("create") == 1
    assert runner.state["status"] == "stopping"
    assert runner.state["resources"][0]["cleanup_failures"] >= 1


def test_作成応答喪失後は同名照合して削除し再送しない(trial, monkeypatch):
    backend = trial[2]
    original = backend.create

    def lost(resource, deployment):
        original(resource, deployment)
        raise ProviderUnavailable("作成応答だけ喪失")

    monkeypatch.setattr(backend, "create", lost)
    runner = runner_for(trial)
    assert drive(runner) == "stopped"
    assert backend.events.count("create") == 1
    assert not backend.pods
    assert runner.state["resources"][0]["status"] == "closed"


@pytest.mark.parametrize("deleted,confirmed", [(False, False), (True, False)])
def test_削除や課金終了が未確認なら完了扱いせず予約を保持する(
    trial,
    monkeypatch,
    deleted,
    confirmed,
):
    runner = runner_for(trial)
    runner.tick()
    monkeypatch.setattr(
        trial[2],
        "close",
        lambda r: {
            "deleted": deleted,
            "billing_confirmed": confirmed,
            "billed_usd": 0,
        },
    )
    runner.stop("test")
    runner.tick()
    assert runner.state["status"] == "stopping"
    assert runner.state["resources"][0]["status"] == "cleanup"


def test_部分成功後の設備障害は確認済み結果を保持し新attemptへ一度再開する(trial):
    runner = runner_for(trial)
    for _ in range(8):
        runner.tick()
    saved = copy.deepcopy(runner.state["results"])
    old = runner.state["resources"][0]["attempt"]
    trial[2].pods.clear()
    assert drive(runner) == "stopped"
    runner.resume()
    assert drive(runner) == "complete"
    assert all(row in runner.state["results"] for row in saved)
    assert len(runner.state["resources"]) == 6
    assert runner.state["resources"][1]["attempt"] != old


def test_設備障害二回なら再開を拒否する(trial):
    runner = runner_for(trial)
    runner.tick()
    trial[2].pods.clear()
    drive(runner)
    runner.resume()
    runner.tick()
    trial[2].pods.clear()
    drive(runner)
    with pytest.raises(ValueError, match="再開"):
        runner.resume()


def test_短いsmokeは各構成3件で残りを欠測として残す(trial):
    trial[1]["purpose"] = "smoke"
    runner = runner_for(trial)
    assert drive(runner) == "complete"
    assert trial[2].events.count("submit") == 15
    assert sum(r["status"] == "missing" for r in runner.state["results"]) == 135
    assert runner.state["synthetic"] is True


def test_測定40分上限で新規処理を止める(trial):
    trial[1].update({"purpose": "measurement", "measurement": True})
    runner = runner_for(trial)
    runner.tick()
    trial[3].seconds += 2400
    assert drive(runner) == "stopped"


def test_構成別USD予約から高単価の時間上限を逆算する():
    d = {"usd_hour": 3, "fixed_usd": 0.2, "time_seconds": 10800}
    assert time_limit("C", d) == pytest.approx((RESERVATIONS["C"] - 0.2) / 3 * 3600)


def profile(rate, speed, fixed=0):
    point = {
        "fixed_usd": 0,
        "usd_hour": rate,
        "fixed_seconds": fixed,
        "seconds_per_image": speed,
        "other_usd": 0,
    }
    return {
        "signature": "same",
        "observed": True,
        "samples": 3,
        "low": point,
        "high": point.copy(),
        "elapsed_seconds": fixed + 3 * speed,
    }


def test_同額なら速い候補を選び費用区間が重なれば基準を維持する():
    base, equal, expensive = profile(1, 720), profile(2, 360), profile(2, 450)
    assert select_candidate(base, equal)
    assert not select_candidate(base, expensive)
    equal["high"]["seconds_per_image"] = 400
    assert not select_candidate(base, equal)


def test_固定費を30件と全量で別々に比較する():
    base, candidate = profile(1.23, 60, 3600), profile(2.14, 20, 3600)
    assert not select_candidate(base, candidate, 30)
    assert select_candidate(base, candidate, 10000)
    assert cost(candidate["high"], 30) / 30 > cost(base["low"], 30) / 30


def test_高単価は同一構成の実測採用根拠なしでは拒否する(trial):
    plan = trial[1]
    plan["deployments"]["A"]["usd_hour"] = 2
    with pytest.raises((ValueError, KeyError)):
        validate_plan(plan)


def test_稼働中の同じ構成を直接二重起動できない(trial):
    runner = runner_for(trial)
    runner.start("A")
    with pytest.raises(ValueError, match="二重起動"):
        runner.start("A")
    assert trial[2].events.count("create") == 1


def test_期限切れで再接続しても終了専用経路は動く(trial):
    runner = runner_for(trial)
    until_sent(runner)
    trial[3].seconds += 4 * 86400
    _, plan, backend, clock = trial
    replacement = Runner(plan, backend, fake=True, clock=clock.now, cleanup_only=True)
    assert replacement.cleanup_only() == "stopped"
    assert not backend.pods
    assert not list((trial[0] / "package").glob("*.png"))


def test_回収後のremote削除失敗を再試行しても結果を二重追加しない(trial, monkeypatch):
    runner = runner_for(trial)
    until_sent(runner)
    backend = trial[2]
    original = backend.remove_image
    calls = 0

    def fail_once(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ProviderUnavailable("削除応答を確認できない")
        return original(*args)

    monkeypatch.setattr(backend, "remove_image", fail_once)
    assert drive(runner) == "complete"
    assert len(runner.state["results"]) == 150


def test_私有レビュー資料の生成は対象件数と地域版費用保持削除範囲をそろえる(trial):
    from colorstats.trial_runner import review_material

    material = review_material(trial[1])
    assert material["count"] == 30
    assert material["hard_usd"] == 15 and material["soft_usd"] == 13
    assert material["external_max_seconds"] == 86400
    assert len(material["models"]) == 5
    assert "required_permission" in material and "unverified" in material
    text = json.dumps(material)
    assert "asset_id" not in text and "source_sha256" not in text


def test_別段階の費用を引き継ぎUSD台帳の総枠をリセットしない(trial):
    root, plan, backend, clock = trial
    with Budget(Path(plan["budget_ledger"]), 15) as budget:
        first = runner_for(trial, budget=budget)
        first.tick()
        first.stop("test")
        drive(first)
        first.state["resources"][0]["estimated_usd"] = 13
        first.save("synthetic_expense")
    root2 = root.parent / "second"
    synthetic_inputs(root2)
    plan2 = synthetic_plan(root2)
    plan2["budget_ledger"] = plan["budget_ledger"]
    backend2 = FakeRunPod(plan2["region"])
    with Budget(Path(plan["budget_ledger"]), 15) as budget:
        second = Runner(plan2, backend2, fake=True, budget=budget, clock=clock.now)
        assert second.spending() >= 13
        assert drive(second) == "stopped"
    assert backend2.events == []


def test_同じUSD台帳の同時利用と総枠変更を拒否する(trial):
    path = Path(trial[1]["budget_ledger"])
    with Budget(path, 15):
        with pytest.raises(BlockingIOError), Budget(path, 15):
            pass
    with pytest.raises(ValueError, match="総枠"), Budget(path, 20):
        pass


def test_CLIの合成実行も共通USD台帳を使う(trial):
    from colorstats.trial_run_cli import execute

    result = execute(trial[1], dry_run=True)
    assert result["status"] == "complete" and result["results"] == 150
    budget = json.loads(Path(trial[1]["budget_ledger"]).read_text())
    assert budget["currency"] == "USD" and budget["cap_usd"] == 15
    assert len(budget["runs"]) == 1


def test_fakeのUSD台帳を実GPUの請求台帳へ流用できない(trial):
    root, plan, _, _ = trial
    with Budget(Path(plan["budget_ledger"]), 15) as budget:
        runner = runner_for(trial, budget=budget)
        state = copy.deepcopy(runner.state)
        state["run_id"] = "separate-run"
        state["synthetic"] = False
        with pytest.raises(ValueError, match="fake"):
            budget.update(state, root)


@pytest.mark.parametrize(
    "status,region", [("PROVISIONING", None), ("STARTING", None), ("RUNNING", "SYNTHETIC")]
)
def test_準備中の未割当地域と空のvolume指定を正常として扱う(trial, status, region):
    runner = runner_for(trial)
    runner.tick()
    pod = next(iter(trial[2].pods.values()))
    pod["status"] = status
    pod["dataCenterId"] = region
    pod["mounts"] = {"persistent": None, "network": [], "global": None}
    runner.tick()
    assert runner.state["stop_reason"] is None
    if status != "RUNNING":
        assert "submit" not in trial[2].events


def test_稼働後の地域欠測や実volume取付けは送信前に拒否する(trial):
    runner = runner_for(trial)
    runner.tick()
    pod = next(iter(trial[2].pods.values()))
    pod["dataCenterId"] = None
    assert drive(runner) == "stopped"
    assert "submit" not in trial[2].events


def test_終了時の遅延請求が構成別予約を超えたら次を起動しない(trial, monkeypatch):
    runner = runner_for(trial)
    runner.tick()
    backend = trial[2]
    original = backend.close

    def expensive(resource):
        receipt = original(resource)
        receipt["billed_usd"] = 2
        return receipt

    monkeypatch.setattr(backend, "close", expensive)
    resource = runner.state["resources"][0]
    runner.cleanup(resource)
    assert runner.state["stop_reason"] == "configuration_budget_exceeded"
    assert drive(runner) == "stopped"
    assert backend.events.count("create") == 1
    assert resource["estimated_usd"] == 2


def test_並列の一方が請求未確認なら全Podを終了し確認後に残りだけ再開する(trial, monkeypatch):
    from colorstats import trial_run_cli

    instances = []

    class BillingWait(FakeRunPod):
        confirmed = False

        def __init__(self, region):
            super().__init__(region)
            instances.append(self)

        def collect(self, pod, resource, trial_id):
            if resource["configuration_id"] == "C" and not self.confirmed:
                return None
            return super().collect(pod, resource, trial_id)

        def close(self, resource):
            receipt = super().close(resource)
            if resource["configuration_id"] == "B" and not self.confirmed:
                receipt["billing_confirmed"] = False
            return receipt

    monkeypatch.setattr(trial_run_cli, "FakeRunPod", BillingWait)
    trial[1]["concurrency"] = 2
    first = trial_run_cli.execute(trial[1], dry_run=True)
    assert first["status"] == "stopping"
    assert first["results"] == 60
    assert not instances[-1].pods
    assert "close" in instances[-1].events
    BillingWait.confirmed = True
    assert trial_run_cli.execute(trial[1], dry_run=True, cleanup=True)["status"] == "stopped"
    assert trial_run_cli.execute(trial[1], dry_run=True, resume=True)["status"] == "complete"
    assert len(read_results(trial[0])[2]) == 150


def test_最終請求確認後は非課金の停止時間を実費へ加算しない(trial, monkeypatch):
    runner = runner_for(trial)
    runner.tick()
    resource = runner.state["resources"][0]
    runner.fake = False
    trial[3].seconds += 10000
    backend = trial[2]
    original = backend.close

    def receipt(resource):
        result = original(resource)
        result["billed_usd"] = 0.25
        return result

    monkeypatch.setattr(backend, "close", receipt)
    runner.cleanup(resource)
    assert resource["estimated_usd"] == resource["billed_usd"] == 0.25


def test_明示的な作成拒否は未確認資源や費用として残さない(trial, monkeypatch):
    from colorstats.trial_runpod import ProviderRejected

    def rejected(*args):
        raise ProviderRejected(402)

    monkeypatch.setattr(trial[2], "create", rejected)
    runner = runner_for(trial)
    assert drive(runner) == "stopped"
    assert runner.state["stop_reason"] == "provider_rejected"
    assert runner.state["resources"][0]["status"] == "closed"
    assert runner.spending() == 0


def test_並列起動の一方が拒否されたら他方を新規起動しない(trial, monkeypatch):
    from colorstats.trial_runpod import ProviderRejected

    trial[1]["concurrency"] = 2
    backend = trial[2]
    original = backend.create
    started = []

    def create(resource, deployment):
        key = resource["configuration_id"]
        started.append(key)
        if key == "B":
            raise ProviderRejected(402)
        return original(resource, deployment)

    monkeypatch.setattr(backend, "create", create)
    runner = runner_for(trial)
    assert drive(runner) == "stopped"
    assert started == ["A", "B"]
    assert not backend.pods


@pytest.mark.parametrize(
    "variant", ["matching", "different_gpu", "expensive_baseline", "synthetic_inputs"]
)
def test_高単価の採用は実測したGPUと低単価の基準へ結ぶ(trial, tmp_path, variant):
    from colorstats.trial_costs import deployment_signature

    plan = trial[1]
    plan["deployments"]["A"]["usd_hour"] = 2
    signature = digest(plan["configurations"]["A"])
    hardware = deployment_signature(plan, "A")

    def record(name, rate, seconds):
        state = {
            "purpose": "measurement",
            "synthetic": False,
            "synthetic_inputs": variant == "synthetic_inputs",
            "status": "complete",
            "nonempty_results": [[f"T{i:03}", "A"] for i in range(3)],
            "resources": [
                {
                    "configuration_id": "A",
                    "status": "closed",
                    "usd_hour": rate,
                    "elapsed_seconds": seconds * 3 + 10,
                    "fixed_usd": 0,
                    "estimated_usd": rate * (seconds * 3 + 10) / 3600,
                    "billed_usd": rate * (seconds * 3 + 10) / 3600,
                    "deployment_sha256": hardware,
                }
            ],
            "results": [
                {
                    "configuration_id": "A",
                    "configuration_sha256": signature,
                    "trial_id": f"T{i:03}",
                    "input_sha256": sha(str(i).encode()),
                    "status": "success",
                    "regions": [{"part": "wall"}],
                    "elapsed_seconds": seconds,
                }
                for i in range(3)
            ],
        }
        path = tmp_path / (name + ".json")
        content = json.dumps(state).encode()
        path.write_bytes(content)
        return {"file": str(path), "sha256": sha(content), "configuration_id": "A"}

    plan["deployments"]["A"]["measurement_evidence"] = {
        "baseline": record("baseline", 3 if variant == "expensive_baseline" else 1, 60),
        "candidate": record("candidate", 2, 10),
    }
    if variant == "different_gpu":
        plan["deployments"]["A"]["gpu"] = "NVIDIA H100 PCIe"
    if variant == "matching":
        validate_plan(plan)
    else:
        with pytest.raises(ValueError, match="採用根拠"):
            validate_plan(plan)


def test_想定外の例外でも作成済みPodの終了を試みる(trial, monkeypatch):
    from colorstats import trial_run_cli

    instances = []

    class Unexpected(FakeRunPod):
        def __init__(self, region):
            super().__init__(region)
            instances.append(self)

        def status(self, resource):
            raise TypeError("synthetic-unexpected")

    monkeypatch.setattr(trial_run_cli, "FakeRunPod", Unexpected)
    result = trial_run_cli.execute(trial[1], dry_run=True)
    assert result["status"] == "stopped"
    assert not instances[0].pods
    assert instances[0].events.count("close") == 1


def test_空maskは受領しても正常非空件数へ数えない(trial):
    import io

    from PIL import Image

    runner = runner_for(trial)
    resource = until_sent(runner)
    key = (resource["attempt"], resource["current"]["trial_id"])
    value, blobs = trial[2].jobs[key]
    width, height = value["size"]
    stream = io.BytesIO()
    Image.new("L", (width, height), 0).save(stream, format="PNG")
    blob = stream.getvalue()
    value["regions"][0]["mask"]["sha256"] = sha(blob)
    blobs["mask-00.png"] = blob
    runner.tick()
    stats = next(r for r in summary(runner.state) if r["configuration_id"] == "A")
    assert len(runner.state["results"]) == 1
    assert stats["nonempty_success_count"] == 0
    assert stats["usd_per_nonempty_success"] is None


@pytest.mark.parametrize("route", ["cleanup_only", "tick"])
def test_清掃中の例外でも並列全Podの終了を試みて失敗を集約する(trial, monkeypatch, route):
    runner = runner_for(trial)
    runner.plan["concurrency"] = 2
    runner.start("B")
    runner.start("C")
    backend = trial[2]
    original = backend.close

    def close(resource):
        receipt = original(resource)
        if resource["configuration_id"] == "B":
            raise ValueError("synthetic-broken-receipt")
        return receipt

    monkeypatch.setattr(backend, "close", close)
    runner.stop("cleanup_requested")
    assert getattr(runner, route)() == "stopping"
    assert not backend.pods
    assert backend.events.count("close") == 2
    assert runner.state["resources"][0]["status"] == "cleanup"
    assert runner.state["resources"][1]["status"] == "closed"
    latest = json.loads(sorted((trial[0] / "execution").glob("*.json"))[-1].read_text())
    assert latest["event"]["detail"]["errors"] == [
        {"configuration_id": "B", "error_type": "ValueError"}
    ]
    runner.cleanup_only()
    assert not backend.pods and runner.state["status"] != "complete"


@pytest.mark.parametrize("past_seconds", [1700, 2400])
def test_別runの測定時間を共通台帳から引き継ぐ(trial, past_seconds):
    root, plan, backend, clock = trial
    plan.update(purpose="measurement", measurement=True)
    with Budget(Path(plan["budget_ledger"]), 20) as budget:
        budget.data["runs"]["prior"] = {
            "synthetic": True,
            "purpose": "measurement",
            "failures": 0,
            "resources": [
                {
                    "status": "closed",
                    "elapsed_seconds": past_seconds,
                    "estimated_usd": 0,
                    "configuration_id": "A",
                }
            ],
        }
        runner = runner_for(trial, budget=budget)
        if past_seconds == 2400:
            with pytest.raises(ValueError, match="40分"):
                runner.start("A")
            assert backend.events == []
        else:
            runner.start("A")
            assert runner.state["resources"][0]["limit_seconds"] == 700


def test_測定leaseは終了余裕を含めて20分以内に終了する(trial):
    trial[1].update(purpose="measurement", measurement=True)
    runner = runner_for(trial)
    runner.start("A")
    assert runner.state["resources"][0]["limit_seconds"] == 1200
    trial[3].seconds = 1170
    assert drive(runner) == "stopped"
    assert not trial[2].pods


def test_最新保持期限を送信先と再開後のローカル削除へ引き継ぐ(trial):
    runner = runner_for(trial)
    resource = until_sent(runner)
    deadline = trial[3].now() + timedelta(seconds=5)
    runner.shorten_retention(deadline)
    assert resource["current"]["deadline"] == deadline.isoformat()
    assert trial[2].events[-1] == "shorten_deadline"
    reopened = runner_for(trial)
    assert reopened.expiry == deadline
    trial[3].seconds += 6
    reopened.cleanup_only()
    assert all(not (trial[0] / row["input"]["file"]).exists() for row in runner.manifest["images"])


def test_権利再確認の戻り値を外部期限へ適用する(trial, monkeypatch, tmp_path):
    from types import SimpleNamespace

    from colorstats import trial_runner

    root, plan, backend, clock = trial
    runner = runner_for(trial)
    resource = until_sent(runner)
    for deployment in plan["deployments"].values():
        for name in ("model", "segmenter"):
            deployment[name]["license_confirmed"] = True
    smoke = tmp_path / "smoke.json"
    smoke.write_text(
        json.dumps(
            {
                "purpose": "smoke",
                "synthetic": False,
                "synthetic_inputs": True,
                "status": "complete",
                "model_settings_sha256": runner.model_signature(),
            }
        )
    )
    plan["smoke_record"] = {"file": str(smoke), "sha256": sha(smoke.read_bytes())}
    runner.fake = False
    runner.manifest["synthetic"] = False
    runner.engine = object()
    runner.budget = SimpleNamespace(verify_smoke=lambda state: None, update=lambda *args: None)
    runner.authorization = {
        "plan_sha256": digest(plan),
        "manifest_sha256": runner.state["manifest_sha256"],
        "provider": "runpod",
        "product": "secure-on-demand",
        "region": plan["region"],
        "send_images": True,
        "billing": True,
        "delete_new_resources": True,
        "retention_confirmed": True,
        "user_text": "test-only",
        "authorized_at": clock.now().isoformat(),
        "expires_at": (clock.now() + timedelta(hours=1)).isoformat(),
        "max_usd": 15,
        "operations": {
            "region": plan["region"],
            "checked_at": clock.now().isoformat(),
            **dict.fromkeys(
                ["status_ref", "maintenance_ref", "capacity_ref", "data_terms_ref"], "a" * 64
            ),
        },
    }
    latest = clock.now() + timedelta(seconds=40)
    calls = []

    def recheck(engine, result_root, *, now):
        calls.append((engine, result_root, now))
        return latest

    monkeypatch.setattr(trial_runner, "recheck", recheck)
    runner.authorize()
    assert calls == [(runner.engine, root, clock.now())]
    assert runner.expiry == latest
    assert resource["current"]["deadline"] == latest.isoformat()


def test_実提供元境界の破損JSONでも全Podを削除要求し再清掃可能にする(trial):
    from colorstats.trial_runpod import RunPod

    runner = runner_for(trial)
    runner.plan["concurrency"] = 2
    runner.start("B")
    runner.start("C")
    alive = {r["id"]: r["name"] for r in runner.state["resources"]}
    receipts = trial[0] / "broken-billing.json"
    receipts.write_text("{broken")
    deleted = []

    def request(method, path, body=None):
        if method == "DELETE":
            key = path.rsplit("/", 1)[-1]
            deleted.append(key)
            del alive[key]
            return {}
        if path == "/pods":
            return {
                "pods": [
                    {"id": key, "name": name, "status": "RUNNING"} for key, name in alive.items()
                ],
                "pagination": {"hasNextPage": False, "nextCursor": None},
            }
        if path == "/network-volumes":
            return {"networkVolumes": [], "pagination": {"hasNextPage": False, "nextCursor": None}}
        if path.startswith("/billing/"):
            return {"records": []}
        key = path.rsplit("/", 1)[-1]
        return {"id": key, "name": alive[key], "status": "RUNNING"}

    runner.backend = RunPod(
        {"billing_receipts": str(receipts)}, audit=lambda e: None, request=request
    )
    assert runner.cleanup_only() == "stopping"
    assert len(deleted) == 2 and not alive
    assert all(r["status"] == "cleanup" for r in runner.state["resources"])
    assert runner.cleanup_only() == "stopping"
    assert len(deleted) == 2
    receipts.write_text(
        json.dumps(
            {
                r["id"]: {"amount_usd": 0, "ended_at": r["created_at"], "evidence_sha256": "a" * 64}
                for r in runner.state["resources"]
            }
        )
    )
    assert runner.cleanup_only() == "stopped"
    assert len(deleted) == 2


def test_元期限72時間から24時間へ短縮しても150件の受領確定まで完了する(trial):
    from colorstats.trial_inputs import stamp

    runner = runner_for(trial)
    original = min(stamp(row["local_expires_at"]) for row in runner.manifest["images"])
    shorter = trial[3].now() + timedelta(hours=24)
    assert original > shorter
    runner.shorten_retention(shorter)
    assert drive(runner) == "complete"
    assert len(read_results(trial[0], now=trial[3].now())[2]) == 150
    ledger = json.loads((trial[0] / "file-ledger.json").read_text())
    masks = [r for r in ledger["files"] if r["file"].startswith("received/")]
    assert len(masks) == 150
    assert all(stamp(mask["expires_at"]) == shorter for mask in masks)
