from copy import deepcopy
from datetime import UTC, datetime

import pytest

from colorstats.stats.licenses import exclusion_reasons
from colorstats.stats.reassess import assessment
from tests.test_analysis_rights import analysis_policy as analysis_policy


def records():
    return ({
        "license_class": "open", "search_provider": "wikimedia_commons",
        "url": "https://upload.wikimedia.org/image.jpg",
        "retrieved_at": datetime(2026, 11, 1, tzinfo=UTC),
        "quality": {"license": "cc-by-sa-4.0", "metadata": {"title": "元meta"}},
    }, {
        "license_class": "open", "site": "wikimedia_commons", "license": "cc-by-sa-4.0",
        "url": "https://commons.wikimedia.org/wiki/File:Image.jpg", "author": None,
        "attribution": None, "policy": {"original": "取得時設定"},
    })


def test_元情報と原本保持を維持し区分だけを解析専用へ接続する(analysis_policy):
    asset, source = records()
    before = deepcopy((asset, source))
    revised, origin, reasons = assessment(asset, source, analysis_policy)
    assert reasons == []
    assert (asset, source) == before
    assert revised["quality"]["license"] == asset["quality"]["license"]
    assert revised["quality"]["metadata"] == asset["quality"]["metadata"]
    assert origin["policy"]["original"] == "取得時設定"
    assert "retention_until" not in revised["quality"]
    assert revised["quality"]["rights"]["access_scope"] == "internal"
    assert revised["quality"]["rights"]["image_redistribution"] is False
    assert assessment(revised, origin, analysis_policy) == (revised, origin, [])
    assert exclusion_reasons(revised, origin, [{
        "license_class": "academic_only", "parameters": {},
    }]) == ["restricted_run"]
    assert exclusion_reasons(revised, origin, [{
        "license_class": "open", "weights_hash": "a" * 64, "parameters": {},
    }]) == ["restricted_weights"]


@pytest.mark.parametrize("condition,reason", [
    ("nc", "noncommercial"), ("unknown", "unknown_license"),
    ("basis", "missing_rights_basis"), ("stop", "rights_use_stopped"),
    ("conflict", "rights_policy_mismatch"), ("origin", "unverified_origin"),
])
def test_除外理由を残して未確認入力を昇格しない(analysis_policy, condition, reason):
    asset, source = records()
    if condition in {"nc", "unknown"}:
        source["license"] = asset["quality"]["license"] = (
            "cc-by-nc-sa-4.0" if condition == "nc" else "CC-BY-SA-4.0"
        )
    elif condition == "basis":
        del analysis_policy["rights_review"]
    elif condition == "stop":
        source["policy"]["use_stopped"] = True
    elif condition == "conflict":
        asset["quality"]["rights"] = {"reviewer": "旧確認"}
    else:
        source["site"] = asset["search_provider"] = "openverse"
    assert reason in assessment(asset, source, analysis_policy)[2]


def test_Openverseは元Commonsの照合を要求する(analysis_policy):
    asset, source = records()
    asset["search_provider"] = source["site"] = "openverse"
    asset["quality"]["metadata"]["source_verified"] = True
    assert assessment(asset, source, analysis_policy)[2] == []
    source["url"] = "https://other.test/wiki/File:Image.jpg"
    assert "unverified_origin" in assessment(asset, source, analysis_policy)[2]
