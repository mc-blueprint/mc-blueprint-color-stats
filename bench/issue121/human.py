"""原画像目視と画像ゲートの照合。個別記録を返さず群別計数だけを集計する。"""

from collections import Counter

from bench.issue121.quality import person_decision

CATEGORIES = ("non_target", "black_and_white", "real_people", "depicted_people")


def fraction(numerator, denominator):
    """分母0を0%にせず、未定義の率として残す。"""
    return {"numerator": numerator, "denominator": denominator,
            "rate": numerator / denominator if denominator else None}


def binary_counts(rows, category, field, *, bad_value=True):
    """明示された正例と問題報告なしの負例を計数し、他分類だけの所見はGT不明に残す。

    subjectの建築/地形GTをこの関数で推測しない。予測null/uncertain・GT不明も別計数する。
    """
    counts = Counter(tp=0, fp=0, fn=0, tn=0, unknown_truth=0, unknown_prediction=0)
    for row in rows:
        categories = row["human_categories"]
        truth = True if category in categories else False if not categories else None
        if category == "real_people" and "depicted_people" in categories:
            truth = False
        if truth is None:
            counts["unknown_truth"] += 1
            continue
        observation = row.get("image_gate_observation") or {}
        value = observation.get(field)
        if value is None or value == "uncertain":
            counts["unknown_prediction"] += 1
            continue
        predicted = value == bad_value
        counts[("tp" if predicted else "fn") if truth else ("fp" if predicted else "tn")] += 1
    return dict(counts)


def summarize(rows):
    """旧/新の無作為群とchallengeを混ぜず、採用漏れと属性単体の見逃しを区別する。

    rowsは私有記録。human_categoriesは確認した所見の分類、採用は固定画像ゲートの状態。
    #119/#118が未提示なら、新契約での統計採用や人物画素の評価へ昇格させない。
    """
    groups = {}
    for name in ("old", "new", "challenge"):
        subset = [row for row in rows if (
            "challenge" if row["group"] == "challenge" else row["cohort"]) == name]
        accepted = [row for row in subset if row["image_gate_verdict"]["decision"] == "accepted"]
        problems = [row for row in subset if row["human_categories"]]
        errors = [row for row in accepted if row["human_categories"]]
        categories = {}
        for category in CATEGORIES:
            positives = [row for row in subset if category in row["human_categories"]]
            escaped = sum(row["image_gate_verdict"]["decision"] == "accepted"
                          for row in positives)
            categories[category] = {
                "human_positive": len(positives),
                "escape_among_reported_positives": fraction(escaped, len(positives)),
                "contamination_among_accepted": fraction(escaped, len(accepted)),
                "escape_among_reviewed": fraction(escaped, len(subset)),
            }
        groups[name] = {"reviewed": len(subset), "accepted": len(accepted),
                        "reported_problems": len(problems),
                        "accepted_reported_problems": len(errors),
                        "verdicts": dict(Counter(row["image_gate_verdict"]["decision"]
                                                 for row in subset)),
                        "categories": categories,
                        "known_label_confusion": {
                            "non_target": binary_counts(subset, "non_target", "target",
                                                        bad_value=False),
                            "black_and_white": binary_counts(subset, "black_and_white",
                                                             "black_and_white"),
                            "real_people": binary_counts(subset, "real_people", "real_people",
                                                         bad_value="present")},
                        "subject_prediction_counts": dict(Counter(
                            (row.get("image_gate_observation") or {}).get("subject", "unknown")
                            for row in subset))}
        if name != "challenge":
            groups[name]["people_decision"] = person_decision(
                selected=len(subset), reviewed=len(subset), accepted=len(accepted),
                missed=categories["real_people"]["escape_among_reported_positives"]["numerator"])
    random_accepted = sum(groups[name]["accepted"] for name in ("old", "new"))
    random_missed = sum(groups[name]["categories"]["real_people"][
        "escape_among_reported_positives"]["numerator"] for name in ("old", "new"))
    return {"groups": groups, "random_people": person_decision(
        selected=sum(groups[name]["reviewed"] for name in ("old", "new")),
        reviewed=sum(groups[name]["reviewed"] for name in ("old", "new")),
        accepted=random_accepted, missed=random_missed),
        "subject_ground_truth": "unverified",
        "statistical_adoption": "unverified_without_privacy_and_region_runs"}
