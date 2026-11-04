"""D15の保守的な統計入力ゲート。画像の削除や法的判断は行わない。"""

import re

from colorstats.rights import analysis_review_reasons


def selected_license(value):
    """収集済みの単一ライセンス表記を比較用に正規化する。"""
    return re.sub(r"[ _]+", "-", value.strip().lower())


def exclusion_reasons(asset, source, runs):
    """選択済み権利と全入力runの制約から除外理由を返す。カテゴリで再選択しない。"""
    reasons = set()
    quality = asset["quality"]
    chosen = selected_license(quality.get("license") or "")
    origin = selected_license(source["license"])
    if not chosen or chosen != origin:
        reasons.add("license_missing_or_mismatch")
    analysis = asset["license_class"] == source["license_class"] == "analysis_only"
    if analysis:
        rights = quality.get("rights", {})
        policy = source.get("policy", {})
        reasons.update(analysis_review_reasons(policy))
        reasons.update(analysis_review_reasons(rights))
        if any(rights.get(key) != policy.get(key) for key in (
            "rights_basis", "rights_review", "attribution_required", "access_scope",
            "image_redistribution", "retention",
        )):
            reasons.add("rights_policy_mismatch")
        if not (source["url"] and asset.get("url") and asset.get("retrieved_at")
                and quality.get("provider") and quality.get("original_id")):
            reasons.add("missing_provenance")
        if rights.get("attribution_required") and not (
            source["attribution"] and (source["author"] or quality.get("author"))
            and quality.get("license_url")
        ):
            reasons.add("missing_attribution")
    if not analysis and any(token in chosen for token in ("-sa", "-nc", "-nd")):
        reasons.add("license_conditions")
    allowed = {"pd", "pdm", "cc0"} | {f"cc-by-{v}" for v in ("1.0", "2.0", "2.5", "3.0", "4.0")}
    if not analysis and chosen not in allowed:
        reasons.add("license_not_allowed")
    if not analysis and (asset["license_class"] != "open" or source["license_class"] != "open"):
        reasons.add("restricted_source")
    if not analysis and (not source["url"] or not source["attribution"]):
        reasons.add("missing_provenance")
    if not analysis and chosen.startswith("cc-by-") and not (
        (source["author"] or quality.get("author")) and quality.get("license_url")
    ):
        reasons.add("missing_attribution")
    for run in runs:
        if run["license_class"] not in ({"open", "analysis_only"} if analysis else {"open"}):
            reasons.add("restricted_run")
        # モデル重みの制約は伝播済みrun列だけに依存しない。
        models = run["parameters"].get("models", {})
        if any(model.get("license_class") != "open" for model in models.values()):
            reasons.add("restricted_weights")
        model = run["parameters"].get("model")
        if model is not None and model.get("license_class") != "open":
            reasons.add("restricted_weights")
        if run.get("weights_hash") and not models and model is None:
            reasons.add("restricted_weights")
    return sorted(reasons)
