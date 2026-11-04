import copy
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse

import pytest
import yaml

from colorstats.stats.subject_attributes import derive, year_range
from colorstats.stats.wikidata import WikidataCatalog
from tests.test_subjects_wikidata import claim

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def rules():
    return yaml.safe_load((ROOT / "configs/subject_attributes.yaml").read_text(encoding="utf-8"))


def date(year, precision=9, **changes):
    return {"time": f"{year:+05d}-00-00T00:00:00Z", "precision": precision,
            "before": 0, "after": 0, "calendarmodel": "http://www.wikidata.org/entity/Q1985727",
            **changes}


def entity(countries=("Q17",), dates=None):
    return {"lastrevid": 42, "claims": {
        "P17": [claim({"id": qid}) for qid in countries],
        "P571": [claim(d) for d in (dates if dates is not None else [date(1600)])],
        "P131": [claim({"id": "Q1490"})],
        "P625": [claim({"latitude": 35.0, "longitude": 139.0})],
        "P31": [claim({"id": "Q41176"})],
    }}


@pytest.mark.parametrize(("year", "expected"), [
    (499, "ancient"), (500, "medieval"), (1499, "medieval"),
    (1500, "early_modern"), (1799, "early_modern"), (1800, "modern"),
])
def test_boundaries_and_same_era_multiple_claims(rules, year, expected):
    value = entity(dates=[date(year), date(year)])
    before = copy.deepcopy(value)
    result = derive(value, rules)
    assert result["region"]["value"] == "japan"
    assert result["era"]["value"] == expected
    assert value == before


@pytest.mark.parametrize(("dates", "reason"), [
    ([date(1499), date(1500)], "conflicting_inceptions"),
    ([date(1500, before=1)], "era_boundary"),
    ([date(1799, after=1)], "era_boundary"),
    ([date(1000, precision=6)], "era_boundary"),
    ([date(-100)], "unsupported_time"),
    ([date(1600, calendarmodel="unknown")], "unsupported_time"),
    ([], "no_inception_claim"),
])
def test_uncertain_dates_stay_unknown(rules, dates, reason):
    result = derive(entity(dates=dates), rules)["era"]
    assert result["state"] == "unknown"
    assert result["value"] is None
    assert result["reason"] == reason


def test_precision_and_qualified_inception(rules):
    assert year_range(date(1750, 8)) == (1750, 1759)
    assert year_range(date(1700, 7)) == (1601, 1700)
    value = entity(dates=[date(1600)])
    value["claims"]["P571"][0]["qualifiers"] = {"P1480": [{"snaktype": "somevalue"}]}
    assert derive(value, rules)["era"]["reason"] == "qualified_inception"


@pytest.mark.parametrize(("time", "precision", "before", "after", "expected", "era"), [
    ("+1800-07-01T00:00:00Z", 11, 1, 1, (1800, 1800), "modern"),
    ("+1799-06-00T00:00:00Z", 10, 1, 1, (1799, 1799), "early_modern"),
    ("+1800-01-01T00:00:00Z", 11, 1, 0, (1799, 1800), None),
    ("+1799-12-31T00:00:00Z", 11, 0, 1, (1799, 1800), None),
    ("+1800-01-00T00:00:00Z", 10, 1, 0, (1799, 1800), None),
    ("+1799-12-00T00:00:00Z", 10, 0, 1, (1799, 1800), None),
    ("+2000-03-01T00:00:00Z", 11, 60, 0, (2000, 2000), "modern"),
    ("+1900-03-01T00:00:00Z", 11, 60, 0, (1899, 1900), "modern"),
    ("+1800-01-01T00:00:00Z", 12, 1, 0, (1799, 1800), None),
    ("+1800-01-01T00:01:00Z", 13, 1, 0, (1800, 1800), "modern"),
    ("+1799-12-31T23:59:59Z", 14, 0, 1, (1799, 1800), None),
])
def test_uncertainty_uses_precision_unit(rules, time, precision, before, after, expected, era):
    value = date(1800, precision, time=time, before=before, after=after)
    assert year_range(value) == expected
    assert derive(entity(dates=[value]), rules)["era"]["value"] == era


@pytest.mark.parametrize(("year", "expected"), [
    (498, "ancient"), (499, None), (500, None), (501, None), (502, "medieval"),
    (1498, "medieval"), (1499, None), (1500, None), (1501, None), (1502, "early_modern"),
    (1798, "early_modern"), (1799, None), (1800, None), (1801, None), (1802, "modern"),
])
def test_julian_years_near_era_boundaries_stay_unknown(rules, year, expected):
    value = date(year, calendarmodel="http://www.wikidata.org/entity/Q1985786")
    result = derive(entity(dates=[value]), rules)["era"]
    assert result["value"] == expected
    if expected is None:
        assert result["reason"] == "julian_era_boundary"


def test_julian_leap_day_and_boundary_with_day_uncertainty(rules):
    value = date(1700, 11, time="+1700-02-29T00:00:00Z", before=59,
                 calendarmodel="http://www.wikidata.org/entity/Q1985786")
    assert year_range(value) == (1700, 1700)
    assert derive(entity(dates=[value]), rules)["era"]["value"] == "early_modern"
    value.update(time="+1799-12-31T00:00:00Z", before=0)
    assert derive(entity(dates=[value]), rules)["era"]["reason"] == "julian_era_boundary"


@pytest.mark.parametrize(("countries", "region", "reason"), [
    (["Q142", "Q183"], "europe", "country_claim"),
    (["Q17", "Q148"], None, "conflicting_countries"),
    (["Q99999999"], None, "unmapped_country"),
    ([], None, "no_country_evidence"),
])
def test_region_requires_mapped_country_not_coordinates(rules, countries, region, reason):
    result = derive(entity(countries=countries), rules)["region"]
    assert result["value"] == region
    assert result["reason"] == reason


def test_deprecated_and_unknown_snaks_are_not_promoted(rules):
    value = entity()
    value["claims"]["P17"].append({"rank": "normal", "mainsnak": {"snaktype": "somevalue"}})
    assert derive(value, rules)["region"]["value"] is None
    value["claims"]["P17"][-1]["rank"] = "deprecated"
    assert derive(value, rules)["region"]["value"] == "japan"


def test_attribute_fetch_reuses_cache_and_projects_four_claims(tmp_path):
    class Client:
        policy = {"maxlag": 5, "user_agent": "fixture"}

        def _get(self, url):
            ids = parse_qs(urlparse(url).query)["ids"][0].split("|")
            return {"entities": {qid: entity() for qid in ids}}

    online = WikidataCatalog({}, tmp_path, client=Client())
    expected = online.attribute_claims(["Q100"])
    assert set(expected["Q100"]["claims"]) == {"P17", "P131", "P625", "P571"}
    assert expected["Q100"]["revision"] == 42

    class Failed(Client):
        def _get(self, url):
            raise URLError("offline")

    cached = WikidataCatalog({}, tmp_path, client=Failed(), offline=True)
    assert cached.attribute_claims(["Q100"]) == expected
    assert cached.requests == online.requests
    with pytest.raises(FileNotFoundError):
        cached.attribute_claims(["Q200"])
