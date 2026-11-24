"""controllerで構成ごとの合成smokeと削除済みUSD台帳を照合する。"""

import json
from pathlib import Path

from colorstats.api_budget import digest
from colorstats.trial_costs import deployment_signature
from colorstats.trial_inputs import private_path, sha
from colorstats.trial_results import load_mask, read_results


def settings_signature(plan, key):
    """他構成を含めず、実行設定とローカルcontrollerの版を固定する。"""
    return digest(
        {
            **{k: plan[k] for k in ("provider", "product", "region")},
            "configuration": plan["configurations"][key],
            "deployment": plan["deployments"][key],
            "controller": {
                name: sha(Path(__file__).with_name(name).read_bytes())
                for name in (
                    "trial_runner.py",
                    "trial_results.py",
                    "trial_smoke.py",
                    "trial_ledger.py",
                    "trial_costs.py",
                    "trial_runpod.py",
                )
            },
        }
    )


def verify_smokes(plan, budget, *, now):
    """選択した各構成の3成功・固定参照・削除を検証する。元記録は更新しない。

    smoke_recordsは構成IDごとの不変checkpointのfile/sha256参照。
    各checkpointは同じUSD台帳のrunと、元の受領結果・manifestに一致する必要がある。
    """
    references = plan.get("smoke_records")
    if references is not None and "smoke_record" in plan:
        raise ValueError("smoke証明は構成別参照か単一参照のどちらかで指定してください")
    if references is None:
        references = dict.fromkeys(plan["configurations"], plan["smoke_record"])
    if set(references) != set(plan["configurations"]):
        raise ValueError("選択構成すべてのsmoke証明が必要です")
    for key, reference in references.items():
        content = Path(reference["file"]).read_bytes()
        if sha(content) != reference["sha256"]:
            raise ValueError("実GPUsmoke記録のSHAが一致しません")
        state = json.loads(content)
        if (
            state["purpose"] not in {"smoke", "measurement"}
            or state["synthetic"] is not False
            or state["synthetic_inputs"] is not True
            or state["status"] != "complete"
            or state.get("configuration_settings_sha256", {}).get(key)
            != settings_signature(plan, key)
        ):
            raise PermissionError("同じ構成の実GPU合成smoke成功記録が必要です")
        run = budget.verify_smoke(state)
        root = Path(run["root"])
        ledger = json.loads((root / "file-ledger.json").read_text(encoding="utf-8"))
        if not any(
            record["file"].startswith("execution/")
            and private_path(root, record["file"]) == Path(reference["file"])
            and record["sha256"] == reference["sha256"]
            for record in ledger["files"]
        ):
            raise ValueError("smoke証明が元の実行台帳に登録されていません")
        manifest, configurations, results = read_results(root, now=now)
        if (
            manifest["synthetic"] is not True
            or sha((root / "manifest.json").read_bytes()) != state["manifest_sha256"]
            or configurations.get(key) != plan["configurations"][key]
            or results != state["results"]
            or sha((root / "results.json").read_bytes()) != state.get("results_sha256")
        ):
            raise ValueError("smokeのmanifest・構成・結果SHAが一致しません")
        rows = [r for r in results if r["configuration_id"] == key and r["status"] != "missing"]
        resources = [r for r in state["resources"] if r["configuration_id"] == key]
        if (
            len(rows) != 3
            or {r["trial_id"] for r in rows} != {"T001", "T002", "T003"}
            or any(
                r["status"] != "success"
                or not any(
                    load_mask(root, region["mask"], r["size"]).any() for region in r["regions"]
                )
                or not any(resource["attempt"] == r["attempt"] for resource in resources)
                for r in rows
            )
            or not resources
            or any(
                not r["id"]
                or r["status"] != "closed"
                or not r["confirmed_deleted"]
                or r["deployment_sha256"] != deployment_signature(plan, key)
                for r in resources
            )
        ):
            raise PermissionError("構成ごとの3成功とsmoke Podの削除確認が必要です")
