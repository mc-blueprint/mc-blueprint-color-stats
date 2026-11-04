import copy
from datetime import UTC, datetime, timedelta
from itertools import product

import pytest

from colorstats.collect.policy import check_policy, license_class
from colorstats.rights import LICENSES, combine_license
from colorstats.stats.licenses import exclusion_reasons


@pytest.fixture
def analysis_policy():
    return {
        "enabled": True, "user_agent": "fixture", "min_interval": 1, "backoff": 5,
        "retries": 0, "attribution": "内部台帳", "redistribution": "画像非配布",
        "license_rules": {"analysis_only": ["all rights reserved", "cc-by-sa-4.0"]},
        "rights_basis": "copyright_act_30_4", "access_scope": "internal",
        "image_redistribution": False, "attribution_required": False,
        "retention": {"raw_days": 30, "rejected_days": 7,
                      "deletion_request_days": 7, "backup_days": 30},
        "rights_review": {
            "reviewed_at": "2026-11-01T00:00:00+00:00", "terms_url": "https://test/terms",
            "api_url": "https://test/api", "robots_url": "https://test/robots.txt",
            "summary": "テスト専用の確認記録", "reviewer": "fixture", "policy_version": "1",
            "purpose": "non_expressive_color_statistics", "decision": "allowed",
        },
    }


def records(policy):
    asset = {
        "license_class": "analysis_only", "url": "https://test/image",
        "retrieved_at": "2026-11-01T00:00:00+00:00", "quality": {
            "license": "all rights reserved", "rights": copy.deepcopy(policy),
            "provider": "fixture", "original_id": "native-1", "author": None,
            "retention_until": "2026-11-02T00:00:00+00:00",
        },
    }
    source = {"license_class": "analysis_only", "license": "all rights reserved",
              "url": "https://test/source", "author": None, "attribution": None,
              "policy": copy.deepcopy(policy)}
    runs = [{"license_class": kind, "parameters": {}} for kind in ("open", "analysis_only")]
    return asset, source, runs


@pytest.mark.parametrize("values", list(product(sorted(LICENSES), repeat=2)))
def test_区分の混在を順序によらず保持する(values):
    restrictions = set(values) - {"open"}
    expected = "restricted" if len(restrictions) > 1 else next(iter(restrictions), "open")
    assert combine_license(*values) == expected
    assert combine_license(*reversed(values)) == expected


def test_帰属不要でも台帳を必須とし原画像期限だけでは統計を失効させない(analysis_policy):
    asset, source, runs = records(analysis_policy)
    before = copy.deepcopy((asset, source, runs))
    check_policy(analysis_policy)
    assert license_class(analysis_policy, "all rights reserved") == "analysis_only"
    assert license_class(analysis_policy, "unknown") == "restricted"
    assert exclusion_reasons(asset, source, runs) == []
    assert (asset, source, runs) == before
    del asset["quality"]["original_id"]
    assert exclusion_reasons(asset, source, runs) == ["missing_provenance"]


@pytest.mark.parametrize("key", ["rights_basis", "rights_review", "retention", "access_scope"])
def test_未確認根拠は取得前と統計入力の両方で拒否する(analysis_policy, key):
    del analysis_policy[key]
    with pytest.raises(ValueError, match="解析専用"):
        check_policy(analysis_policy)
    assert license_class(analysis_policy, "all rights reserved") == "restricted"
    assert "missing_rights_basis" in exclusion_reasons(*records(analysis_policy))


@pytest.mark.parametrize("condition", ["denied", "unknown", "expired", "revoked", "stopped",
                                       "deletion", "future", "invalid_date"])
def test_禁止未確認失効停止は統計に含めない(analysis_policy, condition):
    review = analysis_policy["rights_review"]
    if condition in {"denied", "unknown"}:
        review["decision"] = condition
    elif condition == "expired":
        review["expires_at"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    elif condition == "revoked":
        review["revoked"] = True
    elif condition == "future":
        review["reviewed_at"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    elif condition == "invalid_date":
        review["reviewed_at"] = "未確認"
    else:
        analysis_policy["use_stopped" if condition == "stopped" else "deletion_requested"] = True
    assert exclusion_reasons(*records(analysis_policy))
    assert license_class(analysis_policy, "all rights reserved") == "restricted"


@pytest.mark.parametrize("category", ["noncommercial", "academic_only", "restricted", None])
def test_解析専用でもモデル重みの制約を緩めない(analysis_policy, category):
    asset, source, runs = records(analysis_policy)
    runs[0]["parameters"] = {"models": {"model": {"license_class": category}}}
    assert exclusion_reasons(asset, source, runs) == ["restricted_weights"]
    runs[0]["parameters"] = {"model": {"license_class": category}}
    assert exclusion_reasons(asset, source, runs) == ["restricted_weights"]


def test_SAは明示解析専用だけ許可しsourceの初回根拠は上書きしない(analysis_policy):
    asset, source, runs = records(analysis_policy)
    asset["quality"]["license"] = source["license"] = "cc-by-sa-4.0"
    assert exclusion_reasons(asset, source, runs) == []
    asset["license_class"] = source["license_class"] = "open"
    assert "license_conditions" in exclusion_reasons(asset, source, runs)
    asset["license_class"] = source["license_class"] = "analysis_only"
    source["license"] = "cc0"
    source["policy"]["rights_review"]["policy_version"] = "old"
    assert set(exclusion_reasons(asset, source, runs)) == {
        "license_missing_or_mismatch", "rights_policy_mismatch",
    }


def test_保持承認上限と未知重みを検証する(analysis_policy):
    analysis_policy["retention"]["raw_days"] = 31
    assert "missing_rights_basis" in exclusion_reasons(*records(analysis_policy))
    analysis_policy["retention"]["raw_days"] = 1
    asset, source, runs = records(analysis_policy)
    assert exclusion_reasons(asset, source, runs) == []
    runs[0]["weights_hash"] = "a" * 64
    assert exclusion_reasons(asset, source, runs) == ["restricted_weights"]
