import json
from types import SimpleNamespace

from bench.issue117.production_audit import audit_call

from colorstats.api_budget import digest


def call(tmp_path):
    return SimpleNamespace(details={}, state="unknown", reserved_nusd=1000,
                           cost_nusd=None, response_path=str(tmp_path / "response.json"),
                           response_hash=None, endpoint="responses")


def test_応答のないunknownも予約額を保持して監査を続ける(tmp_path):
    result = audit_call(call(tmp_path))
    assert result == {"basis": "unresolved", "amount_nusd": 1000,
                      "response_present": False, "errors": []}


def test_上限精算した欠損応答を実usageと区別する(tmp_path):
    row = call(tmp_path)
    row.details = {"reconciliation": {"basis": "reservation_upper_bound"}}
    row.cost_nusd, row.state = 1000, "stopped"
    result = audit_call(row)
    assert result == {"basis": "upper_bound", "amount_nusd": 1000,
                      "response_present": False, "errors": []}


def test_精算済みの応答欠損は例外で全体を止めず不一致として返す(tmp_path):
    row = call(tmp_path)
    row.cost_nusd, row.state = 1000, "settled"
    assert audit_call(row)["errors"] == ["missing_settled_response"]


def test_HTTPエラーの上限精算はusageなしでも監査する(tmp_path):
    row = call(tmp_path)
    row.details = {"reconciliation": {"basis": "reservation_upper_bound"}}
    row.cost_nusd, row.state = 1000, "retry"
    envelope = {"status": 520, "body": "upstream failure"}
    row.response_hash = digest(envelope)
    with open(row.response_path, "w", encoding="utf-8") as file:
        json.dump(envelope, file)
    result = audit_call(row)
    assert result["basis"] == "upper_bound" and not result["errors"]
    row.cost_nusd = 0
    assert audit_call(row)["errors"] == ["invalid_upper_bound"]


def test_実usageと応答hashの不一致を見逃さない(tmp_path):
    row = call(tmp_path)
    row.cost_nusd, row.state = 1000, "settled"
    envelope = {"status": 200, "body": json.dumps({"usage": {
        "input_tokens": 10, "output_tokens": 0,
        "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
    }})}
    row.response_hash = digest(envelope)
    with open(row.response_path, "w", encoding="utf-8") as file:
        json.dump(envelope, file)
    assert not audit_call(row)["errors"]
    row.response_hash = "different"
    row.cost_nusd = 0
    assert audit_call(row)["errors"] == ["response_hash_mismatch", "cost_mismatch"]
