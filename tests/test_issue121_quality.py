"""全画素評価で既知負例・空予測・親unionを落とさないことを検証する。"""

import numpy as np
import pytest
from bench.issue121.ade import confusion
from bench.issue121.owned import select
from bench.issue121.quality import aggregate, measure, part_decision, person_decision

GROUPS = {"tree": {"ids": [5], "labels": ["canopy", "trunk"]}}


def test_all_nonvoid_and_parent_union():
    truth = np.array([[0, 2, 3, 5, 13, 5]], dtype=np.uint8)
    mask = np.ones(truth.shape, dtype=bool)
    result = aggregate([measure(truth, [("canopy", mask), ("trunk", mask)],
                                GROUPS, max_id=150)])
    counts = result["groups"]["tree"]
    assert (counts["tp"], counts["fp"], counts["fn"], counts["tn"]) == (2, 3, 0, 0)
    assert counts["precision"] == 0.4
    assert counts["truth_histogram"][0] == 1
    assert result["coverage"]["unmapped_nonvoid_pixels"] == 3
    assert result["coverage"]["group_overlap_pixels"] == 0
    assert part_decision(result["groups"])["tree"]["status"] == "failed"


def test_empty_prediction_is_failure_and_missing_truth_unverified():
    values = aggregate([measure(np.array([[5, 5]]), [], GROUPS, max_id=150)])
    assert values["groups"]["tree"]["fn"] == 2
    assert values["coverage"]["void_rate"] == 1
    assert part_decision(values["groups"])["tree"]["status"] == "failed"
    empty = aggregate([measure(np.array([[0, 3]]), [], GROUPS, max_id=150)])
    assert part_decision(empty["groups"])["tree"]["status"] == "unverified"


def test_boundary_and_invalid_truth():
    value = {"tp": 24, "fp": 6, "fn": 56, "precision": 0.8,
             "recall": 0.3, "iou": 24 / 86}
    assert part_decision({"tree": value})["tree"]["supported"]
    with pytest.raises(ValueError):
        measure(np.array([[151]]), [], GROUPS, max_id=150)


def test_person_denominator_and_incomplete_review():
    value = person_decision(selected=50, reviewed=50, accepted=25, missed=0)
    assert value["status"] == "passed"
    assert value["zero_miss_upper_95"] == pytest.approx(1 - 0.05 ** (1 / 25))
    assert person_decision(selected=50, reviewed=49, accepted=25, missed=0)[
        "status"] == "unverified"
    assert person_decision(selected=50, reviewed=50, accepted=25, missed=1)["status"] == "failed"


def test_owned_excludes_known_sha_alias_and_cross_cohort_duplicates():
    inventory = [{"asset_id": str(i), "cohort": cohort, "sha256": str(i)}
                 for cohort, start in (("old", 0), ("new", 100)) for i in range(start, start + 60)]
    inventory += [{"asset_id": "alias", "cohort": "new", "sha256": "0"},
                  {"asset_id": "cross", "cohort": "new", "sha256": "1"}]
    selected, counts = select(inventory, {"0"}, set())
    assert counts == {"old": 59, "new": 60}
    assert len({row["sha256"] for row in selected}) == 100
    assert [row["number"] for row in selected] == list(range(1, 101))
    assert not {row["asset_id"] for row in selected} & {"0", "alias", "cross"}


def test_ade_annotation_and_model_id_are_offset_once():
    truth = np.array([[0, 3, 13, 150]], dtype=np.uint8)
    predicted = np.array([[2, 2, 12, 149]], dtype=np.uint8)
    matrix = confusion(truth, predicted)
    assert matrix.shape == (151, 150)
    assert matrix[0, 2] == matrix[3, 2] == matrix[13, 12] == matrix[150, 149] == 1
    assert matrix[1:].sum() == 3
