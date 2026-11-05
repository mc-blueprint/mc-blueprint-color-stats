from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from colorstats.stats.supplement import scene_attributes, solar_time

RULES = yaml.safe_load((Path(__file__).resolve().parents[1]
                        / "configs/subject_rules.yaml").read_text(encoding="utf-8"))


def asset(*, date="2020-07-01 12:00:00", point="35,139", categories=(), attrs=None,
          date_source="exif"):
    return SimpleNamespace(scene_attributes=attrs or {}, collected_title="",
                           collected_location=point,
                           quality={"metadata": {"categories": [{"title": "Category:" + c}
                                                                 for c in categories],
                                                 "extmetadata": {"DateTimeOriginal": {
                                                     "value": date, "source": date_source}}}})


def test_date_requires_hemisphere_and_does_not_assume_timezone():
    result, states = scene_attributes(asset(), RULES, {})
    assert result == {"season": "summer"}
    assert states["time_of_day"]["state"] == "unknown"
    assert states["season"]["evidence"][0]["basis"] == "commons_date_gps"
    assert scene_attributes(asset(point="-35,139"), RULES, {})[0] == {"season": "winter"}
    for point in (None, "0,139", "80,139"):
        assert scene_attributes(asset(point=point), RULES, {})[0] == {}


def test_conflicts_and_existing_values_are_not_overwritten():
    result, states = scene_attributes(asset(categories=["Winter in Japan"]), RULES, {})
    assert "season" not in result
    assert states["season"]["state"] == "unknown"
    assert states["season"]["reason"] == "conflicting_evidence"
    result, states = scene_attributes(asset(attrs={"season": "autumn"}), RULES, {})
    assert result["season"] == "autumn"
    assert states["season"]["state"] == "preserved"


def test_categories_and_unknown_placeholder():
    result, states = scene_attributes(asset(point=None, categories=["Forest by day"],
                                           attrs={"time_of_day": "unknown"}), RULES, {})
    assert result["time_of_day"] == "day"
    assert states["time_of_day"]["evidence"][0]["basis"] == "commons_category"
    assert scene_attributes(asset(date="2020-99-99", point="35,139"), RULES, {})[0] == {}


@pytest.mark.parametrize(("hour", "expected"), [(0, "night"), (12, "day")])
def test_solar_utc_day_and_night(hour, expected):
    assert solar_time(datetime(2024, 3, 20, hour, tzinfo=UTC), 0, 0)[0] == expected


def test_exif_utc_enables_time_but_naive_date_does_not():
    image = asset(point="35,0")
    result, states = scene_attributes(image, RULES, {"utc": "2020-07-01T12:00:00+00:00"})
    assert result["time_of_day"] == "day"
    assert states["time_of_day"]["evidence"][0]["basis"] == "exif_utc_solar"
    assert "time_of_day" not in scene_attributes(image, RULES, {"date": "2020:07:01 12:00:00"})[0]


@pytest.mark.parametrize("clocks", [
    {"utc": "2020-07-01T12:00:00+00:00"},
    {"date": "2020:07:01 14:00:00", "offset": "+02:00"},
    {"utc": "2020-07-01T12:00:00+00:00", "date": "2020:07:01 14:00:00",
     "offset": "+02:00"},
    {"date": "2020:07:01 12:00:00Z"},
])
def test_single_and_agreeing_clocks(clocks):
    result, states = scene_attributes(asset(point="35,0"), RULES, clocks)
    assert result["time_of_day"] == "day"
    assert states["time_of_day"]["state"] == "inferred"


def test_disagreeing_clocks_override_category():
    _, states = scene_attributes(asset(point="35,0", categories=["Forest by night"]), RULES,
                                 {"utc": "2020-07-01T00:00:00+00:00",
                                  "date": "2020:07:01 12:00:00", "offset": "+00:00"})
    assert states["time_of_day"]["state"] == "unknown"
    assert states["time_of_day"]["reason"] == "conflicting_utc_evidence"


def test_embedded_offset_is_also_checked_against_gps():
    _, states = scene_attributes(asset(point="35,0"), RULES,
                                 {"utc": "2020-07-01T00:00:00+00:00",
                                  "date": "2020:07:01 12:00:00Z"})
    assert states["time_of_day"]["reason"] == "conflicting_utc_evidence"


@pytest.mark.parametrize("date", ["2020-07-01 to 2020-12-01", "2020-07", "2020",
                                   "2020-07-01 circa", "2020-02-30", "unknown"])
def test_capture_date_must_be_a_single_day(date):
    result, states = scene_attributes(asset(date=date), RULES, {})
    assert "season" not in result
    assert states["season"]["reason"] == "ambiguous_capture_date"


def test_saved_date_requires_capture_proof():
    image = asset(date_source="commons-desc-page")
    result, states = scene_attributes(image, RULES, {})
    assert "season" not in result
    assert states["season"]["reason"] == "unverified_capture_date"
    assert scene_attributes(image, RULES, {"date": "2020:07:01 12:00:00"})[0]["season"] == "summer"


def test_later_conflict_recomputes_owned_value_and_preserves_external_value():
    from colorstats.stats.supplement import METHOD

    image = asset()
    first, states = scene_attributes(image, RULES, {})
    image.scene_attributes = first
    image.quality["scene_inference"] = {"method": METHOD, "attributes": states}
    exif = {"date": "2020:12:01 12:00:00"}
    result, states = scene_attributes(image, RULES, exif)
    assert "season" not in result
    assert states["season"]["state"] == "unknown"
    batch, _ = scene_attributes(asset(), RULES, exif)
    assert batch == result
    assert scene_attributes(asset(attrs={"season": "autumn"}), RULES, exif)[0]["season"] == "autumn"


def test_painting_category_is_not_capture_season():
    image = asset(categories=["Paintings of forests in autumn"])
    result, states = scene_attributes(image, RULES, {})
    assert "season" not in result
    assert states["season"]["reason"] == "nonphotographic_content"
