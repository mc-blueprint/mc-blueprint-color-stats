import copy
import io
import json
from urllib.error import URLError

import pytest

from colorstats.stats.subject_cli import load_rules
from colorstats.stats.subjects import infer
from colorstats.stats.wikidata import ENDPOINT, WIKIDATA, WikidataCatalog
from tests.test_collect import policy as policy
from tests.test_subjects import ROOT, image


@pytest.fixture
def rules():
    result = load_rules(ROOT / "configs/subject_rules.yaml", ROOT / "taxonomy")
    for target in result["subjects"]:
        target.pop("wikidata_id", None)
    return result


def claim(value):
    return {"rank": "normal", "mainsnak": {"snaktype": "value", "datavalue": {"value": value}}}


def entity(name, *, classes=(), parents=(), topic=(), point=True):
    claims = {
        p: [claim({"id": q}) for q in ids]
        for p, ids in [("P31", classes), ("P279", parents), ("P301", topic)]
    }
    if point:
        claims["P625"] = [claim({
            "latitude": 48.58, "longitude": 7.75,
            "globe": "http://www.wikidata.org/entity/Q2",
        })]
    return {"labels": {"en": {"value": name}}, "claims": claims, "lastrevid": 7}


@pytest.fixture
def api():
    return {
        "Q100": entity("Named Tower", classes=["Q101"]),
        "Q101": entity("tower class", parents=["Q41176"], point=False),
        "Q41176": entity("building class", point=False),
        "Q200": entity("Named Mountain", classes=["Q8502"]),
        "Q8502": entity("mountain class", point=False),
        "Q300": entity("Town", classes=["Q56061", "Q41176"]),
        "Q56061": entity("administrative division", point=False),
        "Q400": entity("Category:Named Tower", topic=["Q100"], point=False),
        "Q500": entity("Unnamed class", point=False),
    }


def catalog(api, tmp_path, links=None):
    instance = WikidataCatalog.__new__(WikidataCatalog)
    instance.requests = {}
    instance.client = type("Client", (), {"policy": {"user_agent": "test"}})()
    links = links or {"Named Tower": "Q400", "Named Mountain": "Q200", "Town": "Q300"}

    def query(endpoint, **parameters):
        if endpoint == ENDPOINT:
            return {"query": {"pages": [{
                "title": title, "pageprops": {"wikibase_item": links[title[9:]]}
                if title[9:] in links else {},
            } for title in parameters["titles"].split("|")]}}
        assert endpoint == WIKIDATA
        return {"entities": {q: api[q] for q in parameters["ids"].split("|")}}

    instance.query = query
    return instance


def test_catalog_filters_region_classes_and_missing_coordinates(api, rules, tmp_path):
    api["Q600"] = entity("Missing coordinates", classes=["Q41176"], point=False)
    api["Q41176"] = entity("building class", parents=["Q811979"], point=False)
    api["Q811979"] = entity("architectural structure", point=False)
    links = {
        "Named Tower": "Q400", "Named Mountain": "Q200", "Town": "Q300",
        "Buildings": "Q41176", "No GPS": "Q600",
    }
    result = catalog(api, tmp_path, links).build(links, rules)
    auto = [t for t in result["subjects"] if t["key"].startswith("wikidata:")]
    assert {t["key"] for t in auto} == {"wikidata:Q100", "wikidata:Q200"}
    assert result["wikidata"]["entities"]["Q100"]["revision"] == 7


def test_manual_and_automatic_share_qid_and_original_key(api, rules, tmp_path):
    manual = copy.deepcopy(rules)
    manual["subjects"] = [{
        "key": "preserved-key", "name": "Original name", "domain": "real_building",
        "aliases": ["Original name"], "categories": ["Manual Tower"], "attributes": {},
    }]
    links = {"Manual Tower": "Q100", "Named Tower": "Q400"}
    result = catalog(api, tmp_path, links).build(links, manual)
    assert len(result["subjects"]) == 1
    target = result["subjects"][0]
    assert target["key"] == "preserved-key"
    assert target["wikidata_id"] == "Q100"
    assert set(target["aliases"]) == {"Original name", "Named Tower"}


def test_key_plus_name_or_gps_and_conflicts(api, rules, tmp_path):
    rules = catalog(api, tmp_path).build(["Named Tower", "Town", "Named Mountain"], rules)
    a = image("Named Tower", ["Named Tower"])
    b = image("Unknown", ["Named Tower"], collected_location="48.58,7.75")
    key_only = image("Unknown", ["Named Tower"])
    name_only = image("Named Tower")
    far = image("Named Tower", ["Named Tower"], collected_location="51,-1")
    multi = image("Named Tower", ["Named Tower", "Named Mountain"])
    # 別domainの対象キーが併存する画像も複数対象として保留する。
    mountain = image("Named Mountain", ["Named Mountain"], domain="real_terrain")
    rows, _ = infer([a, b, key_only, name_only, multi, mountain], [], [], [], rules)
    far_rows, _ = infer([far], [], [], [], rules)
    rows.extend(far_rows)
    rows = {r["asset_id"]: r for r in rows}
    assert rows[str(a.id)]["state"] == rows[str(b.id)]["state"] == "confirmed"
    for asset in (key_only, name_only, far):
        assert rows[str(asset.id)]["subject_id"] is None
    assert rows[str(mountain.id)]["state"] == "confirmed"
    assert rows[str(multi.id)]["subject_id"] is None
    assert "multiple_targets" in rows[str(multi.id)]["reasons"]
    assert "location_conflict" in rows[str(far.id)]["reasons"]


def test_same_name_multiple_keys_and_sha_conflict(api, rules, tmp_path):
    api["Q700"] = entity("Named Tower", classes=["Q41176"])
    links = {"Tower A": "Q100", "Tower B": "Q700"}
    rules = catalog(api, tmp_path, links).build(links, rules)
    a = image("Named Tower", ["Tower A", "Tower B"])
    b = image("Named Tower", ["Tower A"], sha="a" * 64)
    c = image("Unknown", ["Tower B"], sha=b.sha256)
    rows, _ = infer([a, b, c], [], [], [], rules)
    assert all(row["subject_id"] is None for row in rows)
    assert "multiple_targets" in rows[0]["reasons"] or any(
        "multiple_targets" in row["reasons"] for row in rows
    )
    assert all(
        "sha_conflict" in row["reasons"]
        for row in rows if row["asset_id"] in (str(b.id), str(c.id))
    )


def test_saved_api_response_is_reused_and_offline_miss_fails(tmp_path):
    class Client:
        policy = {"maxlag": 5}

        def _get(self, url):
            return {"entities": {"Q100": {"lastrevid": 9}}}

    catalog = WikidataCatalog({}, tmp_path, client=Client())
    first = catalog.query(WIKIDATA, action="wbgetentities", ids="Q100")
    assert len(list(tmp_path.glob("*.json"))) == 1
    catalog.offline = True
    assert catalog.query(WIKIDATA, action="wbgetentities", ids="Q100") == first
    with pytest.raises(FileNotFoundError):
        catalog.query(WIKIDATA, action="wbgetentities", ids="Q200")


def test_api_failure_does_not_save_partial_response(tmp_path):
    class Client:
        policy = {"maxlag": 5}

        def _get(self, url):
            raise URLError("offline")

    catalog = WikidataCatalog({}, tmp_path, client=Client())
    with pytest.raises(URLError):
        catalog.query(WIKIDATA, action="wbgetentities", ids="Q100")
    assert list(tmp_path.iterdir()) == []


def test_real_http_client_preserves_user_agent_and_maxlag(tmp_path, policy):
    from colorstats.collect.commons import CommonsAdapter

    seen = []

    def opener(request, timeout):
        seen.append(request)
        response = io.BytesIO(json.dumps({"entities": {}}).encode())
        response.headers = {}
        return response

    p = policy
    client = CommonsAdapter(p, opener=opener, wait=lambda _: None)
    WikidataCatalog(p, tmp_path, client=client).query(
        WIKIDATA, action="wbgetentities", ids="Q100",
    )
    assert seen[0].get_header("User-agent") == p["user_agent"]
    assert "maxlag=" in seen[0].full_url

def test_catalog_is_deterministic_and_rejects_ambiguous_manual_binding(api, rules, tmp_path):
    links = {"Named Tower": "Q400", "Named Mountain": "Q200"}
    first = catalog(api, tmp_path, links).build(links, rules)
    second = catalog(api, tmp_path, links).build(reversed(list(links)), rules)
    assert first == second
    manual = copy.deepcopy(rules)
    manual["subjects"] = [{
        "key": "mixed", "name": "Wrong grouping", "domain": "real_building",
        "categories": ["Tower A", "Tower B"], "aliases": ["Wrong grouping"], "attributes": {},
    }]
    api["Q700"] = entity("Another tower", classes=["Q41176"])
    with pytest.raises(ValueError, match="Wikidata"):
        catalog(api, tmp_path, {"Tower A": "Q100", "Tower B": "Q700"}).build([], manual)

def test_explicit_manual_qid_and_property_links_merge_without_name_matching(api, rules, tmp_path):
    rules["subjects"] = [{
        "key": "stable-manual", "name": "Old spelling", "domain": "real_building",
        "wikidata_id": "Q100", "aliases": ["Old spelling"], "categories": ["Manual detail"],
        "attributes": {},
    }]
    api["Q100"]["claims"]["P373"] = [claim("Saved category")]
    api["Q100"]["claims"]["P910"] = [claim({"id": "Q400"})]
    api["Q400"]["claims"]["P301"] = []
    api["Q400"]["claims"]["P31"] = [claim({"id": "Q4167836"})]
    api["Q4167836"] = entity("Wikimedia category", point=False)
    result = catalog(api, tmp_path, {"Linked category": "Q400"}).build(
        ["Saved category", "Linked category"], rules,
    )
    assert len(result["subjects"]) == 1
    target = result["subjects"][0]
    assert target["key"] == "stable-manual"
    assert set(target["automatic_categories"]) == {"saved category", "linked category"}

def test_additional_keys_cannot_shrink_the_existing_camera_span(rules):
    a = image("Dome of the Rock", ["Facade of the Dome of the Rock"],
              collected_location="31.778,35.235")
    b = image("Dome of the Rock and Another tower",
              ["Facade of the Dome of the Rock", "Another tower"],
              collected_location="40,40")
    before, _ = infer([a, b], [], [], [], rules)
    assert all(row["subject_id"] is None for row in before)
    rules["subjects"].append({
        "key": "wikidata:Q999", "name": "Another tower", "domain": "real_building",
        "aliases": ["Another tower"], "categories": ["Another tower"], "attributes": {},
        "wikidata_id": "Q999", "automatic_categories": ["another tower"],
    })
    after, _ = infer([a, b], [], [], [], rules)
    assert all(row["subject_id"] is None for row in after)


def test_foreground_and_background_named_features_are_not_confirmed(api, rules, tmp_path):
    rules = catalog(api, tmp_path).build(["Named Mountain"], rules)
    asset = image("Glacier lake in front of Named Mountain", ["Named Mountain"],
                  domain="real_terrain")
    rows, _ = infer([asset], [], [], [], rules)
    assert rows[0]["subject_id"] is None
    assert "multiple_targets" in rows[0]["reasons"]

def test_ambiguous_category_blocks_the_otherwise_unique_target(api, rules, tmp_path):
    api["Q700"] = entity("Second Tower", classes=["Q41176"])
    api["Q400"]["claims"]["P301"] = [claim({"id": q}) for q in ("Q100", "Q700")]
    rules = catalog(api, tmp_path, {"Both Towers": "Q400", "Only Tower": "Q100"}).build(
        ["Both Towers", "Only Tower"], rules,
    )
    asset = image("Named Tower", ["Both Towers", "Only Tower"])
    rows, _ = infer([asset], [], [], [], rules)
    assert rows[0]["subject_id"] is None
    assert "multiple_targets" in rows[0]["reasons"]
    assert rows[0]["ambiguous_categories"] == {"both towers": ["Q100", "Q700"]}


@pytest.mark.parametrize("classes", [["Q34442"], ["Q1497364"], ["Q5393308"], ["Q23413"]])
def test_coarse_class_is_candidate_only(api, rules, tmp_path, classes):
    for qid in classes:
        api[qid] = entity("Coarse type", parents=["Q41176"], point=False)
    api["Q100"]["claims"]["P31"] = [claim({"id": q}) for q in classes]
    rules = catalog(api, tmp_path, {"Named Tower": "Q100"}).build(["Named Tower"], rules)
    rows, _ = infer([image("Named Tower", ["Named Tower"])], [], [], [], rules)
    assert rows[0]["subject_id"] is None
    assert "target_granularity" in rows[0]["reasons"]


def test_building_parts_block_but_architectural_elements_do_not(api, rules, tmp_path):
    api["Q700"] = entity("Part A", classes=["Q41176"])
    api["Q701"] = entity("Part B", classes=["Q41176"])
    api["Q100"]["claims"]["P527"] = [claim({"id": q}) for q in ("Q700", "Q701")]
    built = catalog(api, tmp_path, {"Named Tower": "Q100"}).build(["Named Tower"], rules)
    rows, _ = infer([image("Named Tower", ["Named Tower"])], [], [], [], built)
    assert rows[0]["subject_id"] is None
    target = next(t for t in built["subjects"] if t.get("wikidata_id") == "Q100")
    assert target["granularity"]["building_parts"] == ["Q700", "Q701"]
    api["Q391414"] = entity("Architectural element class", point=False)
    api["Q900"] = entity(
        "Architectural element", parents=["Q41176", "Q391414"], point=False,
    )
    for qid in ("Q700", "Q701"):
        api[qid]["claims"]["P31"] = [claim({"id": "Q900"})]
    built = catalog(api, tmp_path, {"Named Tower": "Q100"}).build(["Named Tower"], rules)
    rows, _ = infer([image("Named Tower", ["Named Tower"])], [], [], [], built)
    assert rows[0]["subject_id"]


def test_specific_hall_is_not_the_whole_temple(api, rules, tmp_path):
    api["Q5393308"] = entity("Buddhist temple", parents=["Q41176"], point=False)
    api["Q17051413"] = entity("Main hall", parents=["Q5393308"], point=False)
    api["Q100"]["claims"]["P31"] = [claim({"id": "Q17051413"})]
    built = catalog(api, tmp_path, {"Named Tower": "Q100"}).build(["Named Tower"], rules)
    rows, _ = infer([image("Named Tower", ["Named Tower"])], [], [], [], built)
    assert rows[0]["subject_id"]


@pytest.mark.parametrize("missing", ["category", "entity", "missing_entity_marker"])
def test_incomplete_cached_response_fails_run_input(policy, rules, tmp_path, missing):
    class Client:
        def __init__(self):
            self.policy = policy

        def _get(self, url):
            if "pageprops" in url:
                if missing == "category":
                    return {"query": {"pages": []}}
                return {"query": {"pages": [{
                    "title": "Category:Named Tower", "pageprops": {"wikibase_item": "Q100"},
                }]}}
            return {
                "entities": {"Q100": {"missing": ""}} if missing == "missing_entity_marker" else {},
            }

    rules["subjects"] = []
    first = WikidataCatalog(policy, tmp_path, client=Client())
    with pytest.raises(ValueError, match="欠損"):
        first.build(["Named Tower"], rules)
    # 実通信を行わないキャッシュ読取り経路でも同じ欠損を拒否する。
    cached = WikidataCatalog(policy, tmp_path, offline=True)
    with pytest.raises(ValueError, match="欠損"):
        cached.build(["Named Tower"], rules)


def test_normalized_redirected_and_explicit_missing_category_have_responses(policy, tmp_path):
    class Client:
        def __init__(self):
            self.policy = policy

        def _get(self, url):
            return {"query": {
                "normalized": [{"from": "Category:named tower", "to": "Category:Named tower"}],
                "redirects": [{"from": "Category:Named tower", "to": "Category:Final tower"}],
                "pages": [{"title": "Category:Final tower", "missing": True}],
            }}

    built = WikidataCatalog(policy, tmp_path, client=Client()).build(
        ["named tower"], {"subjects": []},
    )
    assert built["subjects"] == []

@pytest.mark.parametrize("index", [0, 1, 2])
def test_production_granularity_regressions(index, rules, tmp_path):
    recorded = json.loads((ROOT / "tests/fixtures/subject_granularity.json").read_text(
        encoding="utf-8",
    ))
    example = recorded["examples"][index]
    rules["subjects"] = []
    built = catalog(recorded["entities"], tmp_path, {
        example["category"]: example["qid"],
    }).build(example["input"]["categories"], rules)
    asset = image(
        example["input"]["title"], example["input"]["categories"],
        domain=example["domain"], collected_location=example["input"]["location"],
    )
    asset.quality["description"] = example["input"]["description"]
    rows, _ = infer([asset], [], [], [], built)
    assert rows[0]["subject_id"] is None
    assert "target_granularity" in rows[0]["reasons"]
    target = next(t for t in built["subjects"] if t["wikidata_id"] == example["qid"])
    assert target["candidate_only"]

def test_building_class_in_p2670_marks_whole_site_as_coarse(api, rules, tmp_path):
    api["Q710"] = entity("Component building class", parents=["Q41176"], point=False)
    api["Q100"]["claims"]["P2670"] = [claim({"id": "Q710"})]
    built = catalog(api, tmp_path, {"Named Tower": "Q100"}).build(["Named Tower"], rules)
    rows, _ = infer([image("Named Tower", ["Named Tower"])], [], [], [], built)
    assert rows[0]["subject_id"] is None
    assert rows[0]["candidates"]

def test_multiple_metadata_topics_are_not_multiple_physical_targets(api, rules, tmp_path):
    api["Q800"] = entity("Camera manufacturer", point=False)
    api["Q801"] = entity("Camera model", point=False)
    api["Q900"] = entity("Category:Camera metadata", topic=["Q800", "Q801"], point=False)
    built = catalog(api, tmp_path, {"Named Tower": "Q100", "Camera metadata": "Q900"}).build(
        ["Named Tower", "Camera metadata"], rules,
    )
    rows, _ = infer([image("Named Tower", ["Named Tower", "Camera metadata"])], [], [], [], built)
    assert rows[0]["subject_id"]
    assert "camera metadata" not in built["ambiguous_categories"]
    assert built["wikidata"]["category_items"]["camera metadata"] == ["Q800", "Q801"]

def test_natural_feature_parts_do_not_trigger_building_granularity(api, rules, tmp_path):
    api["Q200"]["claims"]["P2670"] = [claim({"id": "Q999999"})]
    built = catalog(api, tmp_path, {"Named Mountain": "Q200"}).build(["Named Mountain"], rules)
    rows, _ = infer([
        image("Named Mountain", ["Named Mountain"], domain="real_terrain"),
    ], [], [], [], built)
    assert rows[0]["subject_id"]

def test_built_structure_type_in_parts_is_not_a_group_of_buildings(api, rules, tmp_path):
    api["Q811979"] = entity("Built structure", point=False)
    api["Q710"] = entity("Architectural component type", parents=["Q811979"], point=False)
    api["Q100"]["claims"]["P2670"] = [claim({"id": "Q710"})]
    built = catalog(api, tmp_path, {"Named Tower": "Q100"}).build(["Named Tower"], rules)
    rows, _ = infer([image("Named Tower", ["Named Tower"])], [], [], [], built)
    assert rows[0]["subject_id"]
