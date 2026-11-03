"""D15の保守的な統計入力ゲート。画像の削除や法的判断は行わない。"""

import re


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
    if any(token in chosen for token in ("-sa", "-nc", "-nd")):
        reasons.add("license_conditions")
    allowed = {"pd", "pdm", "cc0"} | {f"cc-by-{v}" for v in ("1.0", "2.0", "2.5", "3.0", "4.0")}
    if chosen not in allowed:
        reasons.add("license_not_allowed")
    if asset["license_class"] != "open" or source["license_class"] != "open":
        reasons.add("restricted_source")
    if not source["url"] or not source["attribution"]:
        reasons.add("missing_provenance")
    if chosen.startswith("cc-by-") and not (
        (source["author"] or quality.get("author")) and quality.get("license_url")
    ):
        reasons.add("missing_attribution")
    for run in runs:
        if run["license_class"] != "open":
            reasons.add("restricted_run")
        # モデル重みの制約は伝播済みrun列だけに依存しない。
        models = run["parameters"].get("models", {})
        if any(model.get("license_class") != "open" for model in models.values()):
            reasons.add("restricted_weights")
    return sorted(reasons)
