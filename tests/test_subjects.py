import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from colorstats.schema.models import Asset, Subject
from colorstats.stats.subject_cli import load_rules
from colorstats.stats.subjects import METHOD, NAMESPACE, infer, normalize

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def rules():
    return load_rules(ROOT / "configs/subject_rules.yaml", ROOT / "taxonomy")


def image(title=None, categories=(), *, sha=None, domain="real_building", **changes):
    return Asset(
        id=uuid.uuid4(), collected_title=title, domain=domain,
        sha256=sha or uuid.uuid4().hex * 2, scene_attributes={},
        quality={"metadata": {"categories": [{"title": "Category:" + c} for c in categories]}},
        **changes,
    )


def run(assets, rules, subjects=(), duplicates=(), previous=(), **kwargs):
    rows, _ = infer(assets, subjects, duplicates, previous, rules, **kwargs)
    return {r["asset_id"]: r for r in rows}


def test_alias_category_and_unicode(rules):
    a = image("File:Ｓｔｒａｓｂｏｕｒｇ Cathedral 001.jpg",
              ["West facade of Cathédrale Notre-Dame de Strasbourg"])
    row = run([a], rules)[str(a.id)]
    assert row["state"] == "confirmed"
    assert row["scene_attributes"] == {"building_type": "temple"}
    assert normalize("Ａ  B") == "a b"


@pytest.mark.parametrize("title,categories", [
    ("File:Strasbourg Cathedral.jpg", []),
    (None, ["West facade of Cathédrale Notre-Dame de Strasbourg"]),
    ("Unknown", ["Gothic churches in France", "Japan"]),
    (None, []),
])
def test_name_category_or_location_alone_never_confirms(rules, title, categories):
    a = image(title, categories, collected_location="48.58,7.75")
    a.search_parameters = {"collection_bias": {"intended_attributes": {"style": "japanese"}}}
    row = run([a], rules)[str(a.id)]
    assert row["subject_id"] is None
    assert row["scene_attributes"].get("style") != "japanese"


def test_multi_target_and_nearby_separate_buildings(rules):
    a = image("Strasbourg Cathedral and Dome of the Rock",
              ["West facade of Cathédrale Notre-Dame de Strasbourg"])
    b = image("Strasbourg Cathedral", ["West facade of Cathédrale Notre-Dame de Strasbourg"],
              collected_location="48.58,7.75")
    c = image("別棟 north wing", ["Gothic churches in France"],
              collected_location="48.58001,7.75001")
    rows = run([a, b, c], rules)
    assert rows[str(a.id)]["subject_id"] is None
    assert "multiple_targets" in rows[str(a.id)]["reasons"]
    assert rows[str(b.id)]["subject_id"]
    assert rows[str(c.id)]["subject_id"] is None


def test_polysemous_name_location_conflict_and_cross_domain(rules):
    a = image("St. Paul's Cathedral London")
    b = image("St.-Paulus-Dom", ["St. Paul's Cathedral (Münster) at night"],
              collected_location="51.96,7.62")
    c = image("St.-Paulus-Dom", ["St. Paul's Cathedral (Münster) at night"],
              collected_location="51.5,-0.1")
    d = image("St.-Paulus-Dom", ["St. Paul's Cathedral (Münster) at night"],
              domain="real_terrain")
    rows = run([a, b, c, d], rules)
    assert all(row["subject_id"] is None for row in rows.values())
    assert "location_conflict" in rows[str(b.id)]["reasons"]


def test_sha_conflict_keeps_existing_and_phash_never_confirms(rules):
    sid, other = uuid.uuid4(), uuid.uuid4()
    subjects = [
        Subject(id=sid, name="既存A", domain="real_building", scene_attributes={}),
        Subject(id=other, name="既存B", domain="real_building", scene_attributes={}),
    ]
    a, b, c = [image(sha="a" * 64) for _ in range(3)]
    a.subject_id, b.subject_id = sid, other
    near = image()
    pair = SimpleNamespace(method="phash", asset_a=a.id, asset_b=near.id, confidence=0.99)
    rows = run([a, b, c, near], rules, subjects, [pair])
    assert rows[str(a.id)]["subject_id"] == str(sid)
    assert rows[str(b.id)]["subject_id"] == str(other)
    assert rows[str(c.id)]["subject_id"] is None
    assert "sha_conflict" in rows[str(c.id)]["reasons"]
    assert rows[str(near.id)]["state"] == "candidate"


def test_same_sha_inherits_once_and_input_order_does_not_matter(rules):
    a = image("Dome of the Rock", ["Facade of the Dome of the Rock"], sha="a" * 64)
    b = image(sha=a.sha256)
    first = run([a, b], rules)
    second = run([b, a], rules)
    assert first == second
    assert first[str(a.id)]["subject_id"] == first[str(b.id)]["subject_id"]


def test_scene_conflict_existing_values_and_unknown(rules):
    a = image(categories=["Gothic churches in France", "Romanesque churches in France"])
    a.scene_attributes = {"season": "winter"}
    row = run([a], rules)[str(a.id)]
    assert "style" not in row["scene_attributes"]
    assert row["scene_evidence"]["style"]["state"] == "conflict"
    assert row["scene_attributes"]["season"] == "winter"
    assert row["scene_evidence"]["time_of_day"]["state"] == "unknown"


def test_terrain_requires_named_target_and_domain(rules):
    a = image("Sossusvlei", ["Sossusvlei"], domain="real_terrain")
    b = image("Unnamed forest", ["Forests in France"], domain="real_terrain")
    rows = run([a, b], rules)
    assert rows[str(a.id)]["subject_id"]
    assert rows[str(b.id)]["subject_id"] is None



def test_legacy_filename_subject_is_not_a_distinct_target(rules):
    a = image("File:Dome of the Rock (11).jpg", ["Facade of the Dome of the Rock"])
    legacy = Subject(id=uuid.uuid4(), name=a.collected_title, domain=a.domain, scene_attributes={})
    row = run([a], rules, [legacy])[str(a.id)]
    assert row["state"] == "confirmed"
    assert row["subject_id"] != str(legacy.id)
    assert "multiple_targets" not in row["reasons"]



def test_issue41_saved_metadata_regression(rules):
    fixtures = json.loads(
        (ROOT / "tests/fixtures/subject_issue41.json").read_text(encoding="utf-8")
    )
    assets = []
    for item in fixtures:
        raw = item["input"]
        a = image(raw["title"], raw["categories"], sha=item["sha256"],
                  domain=item["domain"], collected_location=raw["location"])
        a.id = uuid.UUID(item["asset_id"])
        a.quality["description"] = raw["description"]
        assets.append(a)
    rows = run(assets, rules)
    confirmed = {}
    for item in fixtures:
        row = rows[item["asset_id"]]
        assert row["state"] == item["expected_state"]
        assert row["subject_id"] == item["expected_subject_id"]
        if row["subject_id"]:
            confirmed.setdefault(row["subject_id"], set()).add(item["group"])
    assert all(len(groups) == 1 for groups in confirmed.values())



def test_external_evidence_is_retained_when_rule_hits_the_same_candidate(rules):
    a = image("Dome of the Rock", ["Facade of the Dome of the Rock"])
    first = run([a], rules)[str(a.id)]
    sid = uuid.UUID(first["subject_id"])
    subject = Subject(id=sid, name="Dome of the Rock", domain=a.domain, scene_attributes={})
    prior = SimpleNamespace(
        asset_id=a.id, subject_id=sid, confidence=0.8,
        evidence={"method": "external", "reason": "確認済みの独立根拠"},
    )
    proof = SimpleNamespace(
        asset_id=a.id, subject_id=sid, confidence=0.95,
        evidence={
            "method": METHOD, "target_key": "dome-of-the-rock", "run_id": "verified",
            "config_hash": "verified-config", "basis": first["candidates"][str(sid)],
        },
    )
    row = run(
        [a], rules, [subject], previous=[proof, prior],
        verified_runs={"verified": "verified-config"},
    )[str(a.id)]
    assert row["candidates"][str(sid)]["previous"] == prior.evidence


@pytest.mark.parametrize("name", ["Dome of the Rock", "File:Dome of the Rock.jpg"])
def test_same_name_is_not_a_verified_target_key(rules, name):
    a = image("Dome of the Rock", ["Facade of the Dome of the Rock"])
    legacy = Subject(id=uuid.uuid4(), name=name, domain=a.domain, scene_attributes={})
    existing = image("別地点の同名対象", subject_id=legacy.id)
    rows = run([a, existing], rules, [legacy])
    assert rows[str(a.id)]["subject_id"] != str(legacy.id)
    assert rows[str(existing.id)]["subject_id"] == str(legacy.id)


def test_deterministic_id_without_key_proof_is_rejected(rules):
    a = image("Dome of the Rock", ["Facade of the Dome of the Rock"])
    sid = uuid.uuid5(NAMESPACE, "real_building:dome-of-the-rock")
    subject = Subject(id=sid, name="Dome of the Rock", domain=a.domain, scene_attributes={})
    with pytest.raises(ValueError, match="確認済み対象キー"):
        run([a], rules, [subject])


def test_legacy_name_reuse_evidence_does_not_verify_an_arbitrary_subject(rules):
    a = image("Dome of the Rock", ["Facade of the Dome of the Rock"])
    first = run([a], rules)[str(a.id)]
    legacy = Subject(id=uuid.uuid4(), name="Dome of the Rock", domain=a.domain, scene_attributes={})
    basis = first["candidates"][first["subject_id"]]
    prior = SimpleNamespace(
        asset_id=a.id, subject_id=legacy.id, confidence=0.95,
        evidence={"method": METHOD, "target_key": "dome-of-the-rock", "run_id": "old",
                  "config_hash": "old-config", "basis": basis},
    )
    row = run([a], rules, [legacy], previous=[prior],
              verified_runs={"old": "old-config"})[str(a.id)]
    assert row["subject_id"] != str(legacy.id)


@pytest.mark.parametrize("reverse", [False, True])
def test_weak_different_target_name_blocks_the_whole_sha_group(rules, reverse):
    a = image("Dome of the Rock", ["Facade of the Dome of the Rock"], sha="a" * 64)
    b = image("Strasbourg Cathedral", sha=a.sha256)
    assets = [b, a] if reverse else [a, b]
    rows = run(assets, rules)
    assert all(r["subject_id"] is None and "sha_conflict" in r["reasons"] for r in rows.values())
    assert len(rows[str(a.id)]["sha_conflicts"]["targets"]) == 2


@pytest.mark.parametrize("description,confirmed", [
    ("Constructed between 1225 and 1264 and rebuilt between 1946 and 1956.", True),
    ("Stone pillars with decorative capitals between the individual windows.", True),
    ("Seen between First House and Second House.", False),
    ("Strasbourg Cathedral is between this building and the river.", False),
])
def test_between_distinguishes_dates_structure_and_target_positions(rules, description, confirmed):
    a = image("Dome of the Rock", ["Facade of the Dome of the Rock"])
    a.quality["description"] = description
    row = run([a], rules)[str(a.id)]
    assert bool(row["subject_id"]) == confirmed


def test_between_production_metadata_regression(rules):
    fixtures = json.loads(
        (ROOT / "tests/fixtures/subject_between.json").read_text(encoding="utf-8")
    )
    for item in fixtures:
        raw = item["input"]
        a = image(raw["title"], raw["categories"], sha=item["sha256"],
                  domain=item["domain"], collected_location=raw["location"])
        a.quality["description"] = raw["description"]
        row = run([a], rules)[str(a.id)]
        assert row["state"] == "confirmed"
        assert row["candidates"][row["subject_id"]]["key"] == item["expected_key"]
