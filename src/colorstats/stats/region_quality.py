"""#121の固定decisionで許可された地形roleだけを統計へ渡す。"""

import hashlib
import json
from pathlib import Path

from colorstats.analyze import region_policy
from colorstats.analyze.segment import _digest

DECISION_SHA256 = "f6a6fabb14a998e472f0ffdf00d0057ec0e563dc22c2478803b943c3a244769a"
FREEZE_DIGEST = "4b67f4cedb9285c9c64771acd4e0c9bfab7eb582a7ee9d537810b6fb2de2435d"
GROUPS = {"real_terrain/tree": ["vegetation_tree_canopy", "tree_trunk"],
          "real_terrain/water": ["water"]}


def load(root):
    """リポジトリの固定根拠を照合した、地形限定のsnapshot品質設定を返す。

    rootはbench/issue121とbench/issue73を含む固定実行コード。根拠の欠落・版違いは拒否する。
    全方式のquality_eligible=falseを維持し、個別の幹・樹冠は支持しない。
    """
    root = Path(root)
    decision_text = (root / "bench/issue121/decision.json").read_text(encoding="utf-8")
    if hashlib.sha256(decision_text.encode()).hexdigest() != DECISION_SHA256:
        raise ValueError("#121の固定decisionが一致しません")
    decision = json.loads(decision_text)
    scope = decision["downstream"]["terrain_only"]
    if (scope["status"] != "passed" or scope["supported_labels"] != ["water"]
            or scope["supported_groups"] != ["real_terrain/tree"]):
        raise ValueError("#121の地形限定契約が一致しません")
    freeze = json.loads((root / "bench/issue121/freeze.json").read_text(encoding="utf-8"))
    if _digest(freeze) != FREEZE_DIGEST:
        raise ValueError("#121の固定freezeが一致しません")
    plan_text = (root / "bench/issue73/plan.json").read_text(encoding="utf-8")
    if hashlib.sha256(plan_text.encode()).hexdigest() != freeze["files"]["bench/issue73/plan.json"]:
        raise ValueError("#121の固定prompt計画が一致しません")
    plan = json.loads(plan_text)
    return {"version": "issue122-terrain-v1",
            "segment": {"method": region_policy.METHOD, "threshold": 0.35,
                        "text_threshold": 0.25,
                        "prompts": plan["source_settings"]["ade"]["prompts"]},
            "quality": {"supported_labels": ["water"],
                        "supported_groups": ["real_terrain/tree"],
                        "quality_eligible_all_parts": False},
            "supported_by_domain": {"real_building": [], "real_terrain": []},
            "group_members": {role: list(members) for role, members in GROUPS.items()},
            "region_validation": {"decision_sha256": DECISION_SHA256, "freeze": freeze,
                                  "prompt_plan": plan_text}}


def approved_roles(quality, parameters):
    """固定したモデル・policy・promptの成功segmentに対して、採用可能なroleを返す。

    新しい品質根拠がない旧呼出しは空集合を返す。指定された根拠・runの不一致はValueError。
    """
    proof = quality.get("region_validation")
    if proof is None:
        return set()
    frozen = proof["freeze"]
    if (proof["decision_sha256"] != DECISION_SHA256 or _digest(frozen) != FREEZE_DIGEST
            or quality.get("group_members") != GROUPS
            or quality.get("supported_by_domain") != {"real_building": [], "real_terrain": []}):
        raise ValueError("地形限定の品質根拠・支持範囲が一致しません")
    plan_text = proof["prompt_plan"]
    if hashlib.sha256(plan_text.encode()).hexdigest() != frozen["files"]["bench/issue73/plan.json"]:
        raise ValueError("地形評価の固定prompt計画が一致しません")
    expected_segment = {"method": region_policy.METHOD, "threshold": 0.35,
                        "text_threshold": 0.25,
                        "prompts": json.loads(plan_text)["source_settings"]["ade"]["prompts"]}
    payload = parameters["payload"]
    if (quality["segment"] != expected_segment
            or parameters["region_policy_hash"] != frozen["policy_hash"]
            or parameters["parent_table"] != frozen["parent_table"]
            or parameters["transform"] != frozen["transform"]
            or any(payload.get(k) != v for k, v in quality["segment"].items())
            or payload["method"] != region_policy.METHOD):
        raise ValueError("品質評価と本番segmentのpolicy・prompt・前処理が一致しません")
    models = parameters["models"]
    if models["oneformer"] != frozen["oneformer"]:
        raise ValueError("品質評価と本番OneFormerが一致しません")
    for name, files in frozen["models"].items():
        expected = {key: value for key, value in files.items()
                    if Path(key).suffix in {".safetensors", ".json", ".txt", ".model"}}
        if models[name]["files"] != expected:
            raise ValueError("品質評価と本番DINO/SAM2が一致しません")
    return set(GROUPS)
