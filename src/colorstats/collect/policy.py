"""未登録ソースと未確認ライセンスを拒否するポリシー。"""

import os
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from colorstats.queue.core import NonRetryableError
from colorstats.rights import analysis_review_reasons


def load_policy(path: Path, provider: str) -> dict:
    """YAMLから有効なソース設定を読む。未登録・無効なら通信前に拒否する。"""
    sources = yaml.safe_load(path.read_text(encoding="utf-8"))["sources"]
    policy = sources.get(provider)
    check_policy(policy)
    return policy


def check_current_source(provider: str) -> None:
    """実行環境の現行policyで許可を再確認する。過去のジョブの許可は流用しない。"""
    path = Path(os.environ.get("COLORSTATS_SOURCE_POLICY", "configs/source_policy.yaml"))
    try:
        load_policy(path, provider)
    except (OSError, ValueError, yaml.YAMLError):
        raise NonRetryableError(f"現行source_policyで{provider}の通信を許可できません") from None


def check_current_url(url: str) -> None:
    """無効ソースのhostを、集約API経由の元ページ・CDN・redirectにも適用する。"""
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    if host == "loc.gov" or host.endswith(".loc.gov"):
        check_current_source("loc")
    elif any(host == domain or host.endswith("." + domain)
             for domain in ("mapillary.com", "fbcdn.net")):
        check_current_source("mapillary")


def host_rate_group(host: str, hosts: dict) -> str:
    """実hostを、HTTP接続先policyと同じsuffix規則で共有枠へ対応付ける。"""
    host = host.lower().rstrip(".")
    for suffix, policy in sorted(hosts.items(), key=lambda item: len(item[0]), reverse=True):
        suffix = suffix.lower().lstrip(".")
        if host == suffix or host.endswith("." + suffix):
            return policy.get("rate_group", host)
    return host


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
    for host, config in policy.get("hosts", {}).items():
        if not host or config.get("kind") not in ("api", "page", "media"):
            raise ValueError("source_policyの接続先区分が不正です")
        if config.get("min_interval", 1) <= 0:
            raise ValueError("host interval must be positive")
        if config.get("max_concurrency", 1) <= 0:
            raise ValueError("host concurrency must be positive")
        for window in config.get("api_windows", []):
            if window["seconds"] <= 0 or window["limit"] <= 0:
                raise ValueError("host API windows must be positive")
        limit = config.get("media_bytes_per_10_seconds")
        if limit is not None and (type(limit) is not int or limit < 0):
            raise ValueError("host media byte limit must be a non-negative integer")
    for window in policy.get("api_windows", []):
        if window["seconds"] <= 0 or window["limit"] <= 0:
            raise ValueError("API rolling枠には正の秒数と要求数が必要です")
    media_limit = policy.get("media_bytes_per_10_seconds")
    if media_limit is not None and (type(media_limit) is not int or media_limit < 0):
        raise ValueError("10秒間の画像転送上限は0以上の整数である必要があります")

    if policy["license_rules"].get("analysis_only") and analysis_review_reasons(policy):
        raise ValueError("解析専用入力の取得根拠が未確認または失効しています")


def license_class(policy: dict, license_name: str) -> str:
    """完全一致の許可リストで判定する。解析専用は別途確認済みの根拠を必須とする。"""
    name = license_name.strip().lower()
    if name in policy["license_rules"].get("analysis_only", []):
        return "analysis_only" if not analysis_review_reasons(policy) else "restricted"
    if "nd" in name.split("-"):
        return "restricted"
    for category in ("open", "noncommercial", "academic_only"):
        if name in policy["license_rules"].get(category, []):
            return category
    return "restricted"
