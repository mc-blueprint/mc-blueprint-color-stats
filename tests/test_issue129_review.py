from bench.issue129.review import counts, summarize


def test_別所見と欠測を陰性へ変えず属性単体の見逃しを数える():
    rows = [
        {"human_categories": ["black_and_white"], "v2_observation": {"black_and_white": False}},
        {"human_categories": [], "v2_observation": {"black_and_white": None}},
        {"human_categories": ["non_target"], "v2_observation": {"black_and_white": False}},
    ]
    assert counts(rows, "black_and_white", "black_and_white", True) == {
        "tp": 0, "fp": 0, "fn": 1, "tn": 0, "unknown_truth": 1, "unknown_prediction": 1,
    }


def test_別理由の除外でも白黒属性の見逃しを隠さず群と低彩度を分離する():
    row = {"group": "random", "cohort": "old", "human_categories": ["black_and_white"],
           "aerial_truth": False, "low_saturation_color": False,
           "v2_observation": {"black_and_white": False},
           "v2_verdict": {"decision": "rejected"}}
    low_color = {**row, "cohort": "new", "human_categories": [],
                 "low_saturation_color": True, "v2_observation": {"black_and_white": True}}
    summary = summarize([row, low_color])
    assert summary["known_black_and_white"] == {"positive": 1, "missed_or_unknown": 1}
    assert summary["low_saturation_color"]["black_and_white_false_positive"] == 1
    assert summary["groups"]["old"]["accepted_reported_problems"] == 0
    assert summary["groups"]["challenge"]["reviewed"] == 0


def test_既知の入力保留も分母に残し新たなAPI欠測と区別する():
    row = {"group": "random", "cohort": "old", "human_categories": [],
           "aerial_truth": False, "low_saturation_color": False,
           "image_gate_run_id": None, "image_gate_verdict": {"reason": "gate_enqueue_failed"},
           "v2_observation": None, "v2_verdict": {"decision": "pending", "reason": "input_hold"}}
    api_failure = {**row, "v2_verdict": {"decision": "pending", "reason": "api_or_job_failure"}}
    result = summarize([row, api_failure])
    assert result["prediction_coverage"] == {
        "total": 2, "observed": 0, "expected_input_holds": 1, "unexpected_unavailable": 1,
    }
    assert result["groups"]["old"]["reviewed"] == 2
    assert result["groups"]["old"]["verdicts"] == {"pending": 2}
