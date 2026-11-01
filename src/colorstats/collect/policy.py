"""未登録ソースと未確認ライセンスを拒否するポリシー。"""

from pathlib import Path

import yaml


def load_policy(path: Path, provider: str) -> dict:
    """YAMLから有効なソース設定を読む。未登録・無効なら通信前に拒否する。"""
    sources = yaml.safe_load(path.read_text(encoding="utf-8"))["sources"]
    policy = sources.get(provider)
    check_policy(policy)
    return policy


def check_policy(policy: dict | None) -> None:
    if not policy or policy.get("enabled") is not True:
        raise ValueError("取得を許可するsource_policyがありません")
    if not policy.get("user_agent") or policy.get("min_interval", 0) <= 0:
        raise ValueError("User-Agentと正の取得間隔が必要です")
    if policy.get("backoff", 0) <= 0 or not 0 <= policy.get("retries", -1) <= 5:
        raise ValueError("正の待機時間と0〜5回の再試行が必要です")
    for key in ("attribution", "redistribution", "license_rules"):
        if not policy.get(key):
            raise ValueError(f"source_policyに{key}が必要です")


def license_class(policy: dict, license_name: str) -> str:
    """完全一致の許可リストで判定する。不明・複合表記・NDはrestricted。"""
    name = license_name.strip().lower()
    if "nd" in name.split("-"):
        return "restricted"
    for category in ("open", "noncommercial", "academic_only"):
        if name in policy["license_rules"].get(category, []):
            return category
    return "restricted"
