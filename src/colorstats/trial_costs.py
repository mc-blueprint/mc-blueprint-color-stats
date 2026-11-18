"""クラウド試行専用のUSD予約と、固定費込みの採用比較。"""

import json
import math
from pathlib import Path

from colorstats.api_budget import digest
from colorstats.trial_inputs import sha

RESERVATIONS = {"A": 1.05, "B": 2.80, "C": 4.20, "D": 1.05, "E": 1.95}
HOURS = {"A": 1.5, "B": 2, "C": 3, "D": 1.5, "E": 1.5}


def number(value):
    """JSONの金額・秒数を有限の非負数として読む。"""
    if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
        raise ValueError("金額・時間は有限の非負数で指定してください")
    return value


def cost(profile, count):
    """固定費、件数比例費、保存等を含む計測区間のUSDを返す。"""
    return (
        number(profile["fixed_usd"])
        + number(profile["usd_hour"])
        * (number(profile["fixed_seconds"]) + count * number(profile["seconds_per_image"]))
        / 3600
        + number(profile["other_usd"])
    )


def select_candidate(baseline, candidate, count=30):
    """実測区間が明確に安いか、同額で速い場合だけ候補を採用する。

    low/highは計測誤差を含む費用式の各端点。区間が重なる場合は基準を使う。
    精度等の同一性はsignatureで照合し、30件と全量を別々に比較する。
    """
    if (
        baseline["signature"] != candidate["signature"]
        or baseline["observed"] is not True
        or candidate["observed"] is not True
        or min(baseline["samples"], candidate["samples"]) < 3
    ):
        raise ValueError("同一構成の3件以上の実測が必要です")
    base_low, base_high = (cost(baseline[k], count) for k in ("low", "high"))
    cand_low, cand_high = (cost(candidate[k], count) for k in ("low", "high"))
    if base_low > base_high or cand_low > cand_high:
        raise ValueError("実測費用区間が逆転しています")
    faster = candidate["elapsed_seconds"] < baseline["elapsed_seconds"]
    exact_equal = base_low == base_high == cand_low == cand_high
    return cand_high < base_low or (exact_equal and faster)


def time_limit(config_id, deployment):
    """再起動分も含む構成別のUSD予約から、実単価で秒上限を逆算する。"""
    rate = number(deployment["usd_hour"])
    fixed = number(deployment["fixed_usd"])
    if rate <= 0 or fixed >= RESERVATIONS[config_id]:
        raise ValueError("構成別の費用予約が不足しています")
    return min(
        HOURS[config_id] * 3600,
        (RESERVATIONS[config_id] - fixed) / rate * 3600,
        number(deployment["time_seconds"]),
    )


def charged(resource, now):
    """起動要求から削除確認までの時計見積と、遅延した請求の大きい方を取る。"""
    seconds = max(resource["elapsed_seconds"], now - resource["started_seconds"])
    rate = max(resource["usd_hour"], resource.get("observed_usd_hour", 0))
    rounded = max(seconds, resource["minimum_seconds"])
    return max(resource["billed_usd"], resource["fixed_usd"] + rounded * rate / 3600)


def summary(state):
    """失敗・再試行・固定費込みの構成別USD/予定件数・正常件数を集計する。"""
    rows = []
    nonempty = {tuple(key) for key in state["nonempty_results"]}
    for key in "ABCDE":
        expenses = [r for r in state["resources"] if r["configuration_id"] == key]
        total = sum(r["estimated_usd"] for r in expenses)
        success = sum(
            r["configuration_id"] == key
            and r["status"] == "success"
            and (r["trial_id"], key) in nonempty
            for r in state["results"]
        )
        rows.append(
            {
                "configuration_id": key,
                "estimated_usd": total,
                "billed_usd": sum(r["billed_usd"] for r in expenses),
                "planned_count": 30,
                "nonempty_success_count": success,
                "usd_per_planned": total / 30,
                "usd_per_nonempty_success": total / success if success else None,
            }
        )
    return rows


def measured_profile(record):
    """実GPU測定の確定checkpointから、固定費と写真単位の処理区間を得る。"""
    content = Path(record["file"]).read_bytes()
    state = json.loads(content)
    if (
        sha(content) != record["sha256"]
        or state["purpose"] != "measurement"
        or state["synthetic"] is not False
        or state["synthetic_inputs"] is not False
        or state["status"] != "complete"
    ):
        raise ValueError("高単価の採用根拠には実GPU・実写入力で完了した測定checkpointが必要です")
    key = record["configuration_id"]
    nonempty = {tuple(item) for item in state["nonempty_results"]}
    results = [
        r
        for r in state["results"]
        if r["configuration_id"] == key
        and r["status"] == "success"
        and (r["trial_id"], key) in nonempty
    ]
    resources = [r for r in state["resources"] if r["configuration_id"] == key]
    if len(results) < 3 or not resources or any(r["status"] != "closed" for r in resources):
        raise ValueError("回収・削除・請求を確認した正常3件以上の測定が必要です")
    rates = {r["usd_hour"] for r in resources}
    signatures = {r["configuration_sha256"] for r in results}
    hardware = {r["deployment_sha256"] for r in resources}
    if len(rates) != 1 or len(signatures) != 1 or len(hardware) != 1:
        raise ValueError("測定内の単価・構成が混在しています")
    elapsed = sum(number(r["elapsed_seconds"]) for r in resources)
    times = [number(r["elapsed_seconds"]) for r in results]
    rate = rates.pop()
    total = sum(number(r["billed_usd"]) for r in resources)
    fixed_usd = max(0, total - rate * sum(times) / 3600)
    fixed = 0
    other = 0
    base = {"fixed_usd": fixed_usd, "usd_hour": rate, "fixed_seconds": fixed, "other_usd": other}
    return {
        "signature": signatures.pop(),
        "deployment_sha256": hardware.pop(),
        "observed": True,
        "samples": len(times),
        "inputs_sha256": digest(sorted(r["input_sha256"] for r in results)),
        "elapsed_seconds": elapsed,
        "source_sha256": record["sha256"],
        "low": {**base, "seconds_per_image": min(times)},
        "high": {**base, "seconds_per_image": max(times)},
    }


def deployment_signature(plan, key):
    """測定したGPU・container・単価を、採用する構成へ結ぶ。"""
    deployment = plan["deployments"][key]
    return digest(
        {
            "provider": plan["provider"],
            "product": plan["product"],
            "region": plan["region"],
            **{
                k: deployment[k]
                for k in (
                    "registry",
                    "min_cuda_version",
                    "gpu",
                    "gpu_count",
                    "container",
                    "memory_fraction",
                    "usd_hour",
                    "fixed_usd",
                    "minimum_seconds",
                    "hourly_extras_usd",
                )
            },
        }
    )
