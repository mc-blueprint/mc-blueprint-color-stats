import copy
import json
from pathlib import Path

import jsonschema
import numpy as np
import pytest

from colorstats.judgment_inputs import draft_mask, summarize_judgments, validate_judgment


def test_summary_uses_region_weights_label_sets_and_exact_names():
    inputs = {aid: {"regions": [{"draft_id": str(i), "label": "wall_main"}
                                for i in range(count)]}
              for aid, count in (("a", 3), ("b", 1), ("empty", 0))}
    rows = {aid: {"domain": "real_building" if aid == "a" else "real_terrain",
                  "stratum": "test", "building_id": "candidate" if aid == "a" else "",
                  "building_evidence": "候補根拠", "title": "タイトル", "source_url": "url"}
            for aid in inputs}
    first = {aid: {"regions": [{"draft_id": str(i), "verdict": "correct"}
                               for i in range(len(image["regions"]))],
                   "missed_major_parts": [{"label": "roof_surface"}] if aid == "a" else [],
                   "building_name": "名称" if aid == "a" else None, "evidence": ["根拠"]}
             for aid, image in inputs.items()}
    repeat = copy.deepcopy(first)
    repeat["a"]["regions"].reverse()
    repeat["a"]["regions"][0]["verdict"] = "spill"
    repeat["a"]["missed_major_parts"] *= 2
    repeat["b"]["regions"][0]["verdict"] = "not_present"
    repeat["a"]["building_name"] = "別名"
    original = copy.deepcopy(first)
    summary, identity = summarize_judgments(inputs, first, repeat, rows)
    assert summary["repeat"]["verdict"] == {"matches": 2, "total": 4, "rate": 0.5}
    assert summary["repeat"]["images"]["a"]["verdict"]["rate"] == pytest.approx(2 / 3)
    assert summary["repeat"]["images"]["empty"]["verdict"]["rate"] is None
    assert summary["images"]["empty"]["rates"]["correct"] is None
    assert summary["repeat"]["missed_major_parts"]["rate"] == 1
    assert summary["repeat"]["building_name"]["rate"] == pytest.approx(2 / 3)
    assert summary["overall"]["counts"]["correct"] == 4
    assert summary["domains"]["real_terrain"]["images"] == 2
    assert summary["missed_major_parts"] == {"roof_surface": 1}
    assert identity["assets"]["a"]["evidence"] == ["根拠"]
    assert first == original
    repeat["a"]["regions"].pop()
    with pytest.raises(ValueError, match="draft_id"):
        summarize_judgments(inputs, first, repeat, rows)


def test_identity_reports_group_splits_merges_and_unresolved_candidates():
    names = {"a": "建築A", "b": "建築A", "c": "建築B", "d": "建築C",
             "e": None, "f": "建築A"}
    ids = {"a": "one", "b": "one", "c": "two", "d": "two", "e": "three", "f": "four"}
    inputs = {aid: {"regions": []} for aid in names}
    first = {aid: {"regions": [], "missed_major_parts": [], "building_name": name,
                   "evidence": ["根拠"]} for aid, name in names.items()}
    rows = {aid: {"domain": "real_building", "stratum": "test", "building_id": ids[aid],
                  "building_evidence": "候補", "title": "タイトル", "source_url": "url"}
            for aid in names}
    _, identity = summarize_judgments(inputs, first, {}, rows)
    assert all(identity["assets"][aid]["comparison"] == "mismatch" for aid in "abcdf")
    assert identity["assets"]["e"]["comparison"] == "unresolved"
    first["f"]["building_name"] = "建築D"
    _, identity = summarize_judgments(inputs, first, {}, rows)
    assert identity["assets"]["a"]["comparison"] == "match"
    assert identity["assets"]["b"]["comparison"] == "match"
    assert identity["assets"]["f"]["comparison"] == "not_grouped"


def test_rle_holes_and_coordinate_system():
    shape = {"left": "1", "top": "2", "width": "3", "height": "2", "rle": "0,2,2,2"}
    expected = np.zeros((5, 7), dtype=bool)
    expected[2, 1:3] = True
    expected[3, 2:4] = True
    np.testing.assert_array_equal(draft_mask(shape, (7, 5)), expected)
    with pytest.raises(ValueError):
        draft_mask({**shape, "rle": "0,7"}, (7, 5))


def test_result_schema_and_complete_coverage():
    schema = json.loads(Path("bench/issue41/judgment.schema.json").read_text(encoding="utf-8"))
    inputs = {"batch_id": "batch-01", "images": [
        {"asset_id": "a", "regions": [{"draft_id": "0:0"}, {"draft_id": "0:1"}]},
        {"asset_id": "b", "regions": []},
    ]}
    result = {
        "batch_id": "batch-01", "model": "gpt-6.1-sol", "execution_id": "test",
        "repeat_of": None, "images": [
            {"asset_id": image["asset_id"], "regions": [
                {**r, "verdict": "wrong_label", "evidence": "テスト"} for r in image["regions"]
            ], "missed_major_parts": [], "building_name": None, "evidence": []}
            for image in inputs["images"]
        ],
    }
    validate_judgment(result, inputs, schema)
    missing = copy.deepcopy(result)
    missing["images"][0]["regions"].pop()
    with pytest.raises(ValueError, match="過不足"):
        validate_judgment(missing, inputs, schema)
    duplicate = copy.deepcopy(result)
    duplicate["images"][0]["regions"].append(duplicate["images"][0]["regions"][0])
    with pytest.raises(ValueError, match="重複"):
        validate_judgment(duplicate, inputs, schema)
    invalid = copy.deepcopy(result)
    invalid["images"][0]["regions"][0]["verdict"] = "unknown"
    with pytest.raises(jsonschema.ValidationError):
        validate_judgment(invalid, inputs, schema)
