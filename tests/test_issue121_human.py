"""保留を採用漏れに数えず、絵の人物を実在人物へ変換しないことを確認する。"""

from bench.issue121.decision import apply_human
from bench.issue121.human import binary_counts, fraction, summarize


def row(cohort, decision, categories, observation=None, *, group="random"):
    return {"cohort": cohort, "group": group, "human_categories": categories,
            "image_gate_verdict": {"decision": decision},
            "image_gate_observation": observation or {}}


def test_pending_or_rejected_is_not_accepted_escape():
    rows = [row("old", "accepted", []),
            row("old", "pending", ["real_people"], {"real_people": "present"}),
            row("old", "rejected", ["black_and_white"], {"black_and_white": False}),
            row("new", "accepted", ["non_target"], {"target": True}),
            row("new", "accepted", ["real_people"], {"real_people": "absent"}, group="challenge")]
    result = summarize(rows)
    assert result["groups"]["old"]["accepted_reported_problems"] == 0
    assert result["groups"]["old"]["categories"]["real_people"][
        "escape_among_reported_positives"] == fraction(0, 1)
    assert result["groups"]["old"]["known_label_confusion"]["black_and_white"]["fn"] == 1
    assert result["groups"]["new"]["categories"]["non_target"][
        "contamination_among_accepted"] == fraction(1, 1)
    assert result["random_people"]["missed"] == 0
    assert result["groups"]["challenge"]["categories"]["real_people"][
        "escape_among_reported_positives"] == fraction(1, 1)


def test_other_problem_categories_are_not_invented_negative_labels():
    counts = binary_counts([
        row("old", "rejected", ["non_target"], {"black_and_white": True}),
        row("old", "pending", ["black_and_white"], {"black_and_white": None}),
        row("old", "accepted", [], {"black_and_white": False}),
    ], "black_and_white", "black_and_white")
    assert counts == {"tp": 0, "fp": 0, "fn": 0, "tn": 1,
                      "unknown_truth": 1, "unknown_prediction": 1}


def test_depicted_person_is_not_real_person_and_empty_denominator_is_unknown():
    counts = binary_counts([
        row("old", "rejected", ["depicted_people", "non_target"], {"real_people": "absent"})
    ], "real_people", "real_people", bad_value="present")
    assert counts["tn"] == 1 and counts["fn"] == 0
    assert fraction(0, 0)["rate"] is None


def test_accepted_gate_review_does_not_approve_missing_privacy_region_contracts():
    rows = [row(name, "accepted", []) for name in ("old", "new") for _ in range(50)]
    rows += [row("new", "rejected", ["non_target"], group="challenge") for _ in range(10)]
    human = {**summarize(rows), "review_count": 110, "problem_count": 10,
             "presentation_images": 110, "external_references": 0, "data_uri_decoded": 110,
             "presentation_sha256": "test", "completion_explicit_in_original": False,
             "completion_basis": "依頼に基づく仮定", "import_status": "missing_presented_runs",
             "human_runs_written": 0, "privacy_run_references": 0,
             "region_policy_run_references": 0}
    result = apply_human({"criteria": {}, "downstream": {}, "quality_eligible": False}, human)
    assert result["criteria"]["content_acceptance"]["status"] == "passed"
    assert result["criteria"]["image_gate_people"]["status"] == "passed"
    assert result["criteria"]["privacy_region_contract"]["status"] == "unverified"
    assert result["criteria"]["human_review_recording"]["status"] == "unverified"
    assert result["quality_eligible"] is False
