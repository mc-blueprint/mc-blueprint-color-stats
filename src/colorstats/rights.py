"""入力区分の合成と解析専用入力の確認記録。画像の利用許諾は変更しない。"""

from datetime import UTC, datetime

LICENSES = {"open", "analysis_only", "noncommercial", "academic_only", "restricted"}


def combine_license(*values: str) -> str:
    """openを中立として合成する。異なる非open制約の混在・未知値はrestricted。"""
    restrictions = set(values) - {"open"}
    if set(values) - LICENSES or len(restrictions) > 1:
        return "restricted"
    return next(iter(restrictions)) if restrictions else "open"


def analysis_review_reasons(policy: dict, *, now: datetime | None = None) -> list[str]:
    """固定policyの解析根拠を検証する。保存期限は統計利用の失効日として扱わない。

    rights_reviewのexpires_atは任意の統計利用期限（タイムゾーン付きISO時刻）。
    利用停止・削除要求はpolicyまたは取得時rightsに同じキーで記録する。
    """
    reasons = set()
    review = policy.get("rights_review") or {}
    retention = policy.get("retention") or {}
    if (
        policy.get("rights_basis") != "copyright_act_30_4"
        or policy.get("access_scope") != "internal"
        or policy.get("image_redistribution") is not False
        or not isinstance(policy.get("attribution_required"), bool)
        or not all(review.get(key) for key in (
            "reviewed_at", "terms_url", "api_url", "robots_url", "summary", "reviewer",
            "policy_version",
        ))
        or review.get("purpose") != "non_expressive_color_statistics"
        or review.get("decision") != "allowed"
        or any(not isinstance(retention.get(key), int) or not 0 < retention[key] <= limit
               for key, limit in (("raw_days", 30), ("rejected_days", 7),
                                  ("deletion_request_days", 7), ("backup_days", 30)))
    ):
        reasons.add("missing_rights_basis")
    if policy.get("use_stopped") or policy.get("deletion_requested"):
        reasons.add("rights_use_stopped")
    if review.get("revoked"):
        reasons.add("rights_basis_expired")
    for key in ("reviewed_at", "expires_at"):
        value = review.get(key)
        if value:
            try:
                stamp = datetime.fromisoformat(value)
                if stamp.tzinfo is None:
                    raise ValueError
                current = now or datetime.now(UTC)
                if key == "expires_at" and stamp <= current:
                    reasons.add("rights_basis_expired")
                if key == "reviewed_at" and stamp > current:
                    reasons.add("missing_rights_basis")
            except (TypeError, ValueError):
                reasons.add("missing_rights_basis")
    return sorted(reasons)
