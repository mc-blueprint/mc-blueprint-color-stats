import pytest

from colorstats.segmentation_quality import adoption, label_support, split_groups


def test_split_keeps_transitive_sha_and_subject_groups():
    rows = [
        {"id": "a", "sha256": "1", "subject_id": None},
        {"id": "b", "sha256": "1", "subject_id": "s"},
        {"id": "c", "sha256": "2", "subject_id": "s"},
        {"id": "d", "sha256": "3", "subject_id": None},
    ]
    result = split_groups(rows)
    assert result["a"] == result["b"] == result["c"]
    assert result == split_groups(list(reversed(rows)))


def report(value):
    return {dataset: {label: {"iou": value, "precision": value, "tp": 1}
                      for label in labels} for dataset, labels in {
        "cmp": ["band_course", "cornice", "relief", "wall", "window", "door", "column"],
        "ade": ["water", "door"],
    }.items()}


def test_adoption_requires_all_gates_and_rejects_missing_values():
    baseline, candidate = report(0.2), report(0.23)
    assert adoption(baseline, candidate)["accepted"]
    candidate["cmp"]["wall"]["precision"] = 0.21
    assert not adoption(baseline, candidate)["accepted"]
    candidate = report(0.23)
    candidate["ade"]["water"]["iou"] = 0.1
    assert not adoption(baseline, candidate)["checks"]["ade_iou"]
    candidate["ade"]["water"]["iou"] = None
    assert not adoption(baseline, candidate)["accepted"]


@pytest.mark.parametrize("value,expected", [(0.5, True), (0.4999, False), (None, False)])
def test_support_does_not_promote_group_union_or_unmapped(value, expected):
    mapping = {"datasets": {"cmp": {"groups": {
        "wall": {"labels": ["wall_main", "wall_secondary"]},
        "door": {"labels": ["door"]},
    }}}}
    reports = {"cmp": {"wall": {"precision": 0.9, "tp": 50},
                       "door": {"precision": value, "tp": 1}}}
    result = label_support(reports, mapping, ["door", "wall_main", "roof_surface"])
    assert result["door"]["supported"] == expected
    assert result["wall_main"]["status"] == "group_only"
    assert result["roof_surface"]["status"] == "unmapped"


def test_support_requires_all_corresponding_datasets():
    mapping = {"datasets": {d: {"groups": {"door": {"labels": ["door"]}}}
                            for d in ("cmp", "ade")}}
    reports = {"cmp": {"door": {"precision": 0.9, "tp": 20}},
               "ade": {"door": {"precision": 0.4, "tp": 10}}}
    assert not label_support(reports, mapping, ["door"])["door"]["supported"]


def test_adoption_exact_gain_boundary():
    assert adoption(report(0.2), report(0.22))["accepted"]
    assert not adoption(report(0.2), report(0.219999))["accepted"]
