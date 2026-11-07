import json
from pathlib import Path

from bench.issue118.select_inputs import digest, select
from bench.issue118.smoke import summarize
from PIL import Image


def test_selection_is_fixed_and_keeps_people_and_off_target_out(tmp_path):
    rows = []
    for index in range(8):
        image = tmp_path / f"source-{index}.png"
        Image.new("RGB", (8, 6), (index * 20, 80, 100)).save(image)
        rows.append({"asset_id": str(index), "prep_status": "succeeded",
                     "input_path": str(image), "input_sha256": digest(image),
                     "person_mask": "person.png" if index == 5 else None})
    flags = [{"asset_id": row["asset_id"], "sky_building": i < 3, "overlap_reported": True,
              "reason": "person_not_detected", "off_target": i == 6, "person_missed": i == 7}
             for i, row in enumerate(rows)]
    cohort = tmp_path / "cohort.json"
    cohort.write_text(json.dumps({"assets": rows}))
    known = tmp_path / "known.json"
    known.write_text(json.dumps(flags))
    original = {row["input_path"]: Path(row["input_path"]).read_bytes() for row in rows}
    first = select([cohort], known, tmp_path / "first")
    second = select([cohort], known, tmp_path / "second")
    assert first == second and first["eligible"] == 5
    assert len({row["asset_id"] for row in first["assets"]}) == 3
    assert all(int(row["asset_id"]) < 5 for row in first["assets"])
    assert first["assets"][0]["known"]["sky_building"]
    for row in first["assets"]:
        assert digest(tmp_path / "first" / row["file"]) == row["input_sha256"]
    assert all(Path(path).read_bytes() == data for path, data in original.items())
    extra = select([cohort], known, tmp_path / "extra", previous=tmp_path / "first/selection.json",
                   seed=11820261108, count=2)
    assert len(extra["assets"]) == 2
    assert not ({row["input_sha256"] for row in first["assets"]}
                & {row["input_sha256"] for row in extra["assets"]})


def test_aggregate_reports_void_and_does_not_expose_image_identifiers():
    record = {"status": "succeeded", "sample_id": "private-id", "input_sha256": "private-sha",
              "known": {"sky_building": True, "overlap_reported": True}, "seconds": 2,
              "metrics": {"peak_allocated_bytes": 20, "oneformer_peak_allocated_bytes": 10},
              "comparison": {"pixels": 100, "sky_pixels": 40, "raw_building_pixels": 90,
                             "effective_building_pixels": 20, "effective_terrain_pixels": 10,
                             "sky_building_before": 30,
                             "sky_building_after": 0, "building_terrain_before": 10,
                             "building_terrain_after": 0, "effective_pixels": 30,
                             "void_pixels": 70}}
    result = summarize([record])
    assert result["rates"]["sky_building_before_image_rate"] == 0.3
    assert result["rates"]["void_pixels_image_rate"] == 0.7
    assert result["rates"]["effective_building_pixels_image_rate"] == 0.2
    assert result["rates"]["effective_terrain_pixels_image_rate"] == 0.1
    assert result["known_cases"]["sky_building"] == {
        "cases": 1, "positive_before": 1, "positive_after": 0,
    }
    assert "private-" not in json.dumps(result)
    assert summarize([])["rates"]["effective_pixels_image_rate"] is None
