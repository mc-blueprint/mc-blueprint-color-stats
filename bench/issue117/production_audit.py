"""本番台帳の保存応答監査。欠損応答を読み飛ばす際も費用区分を失わない。"""

import json
from pathlib import Path

from colorstats.api_budget import digest, usage_cost


def audit_call(call):
    """要求1件の費用根拠と固定エラーコードを返す。DB更新・再送はしない。

    basisはusage・upper_bound・unresolved。応答がない未精算要求は予約額を返し、
    手動精算の上限額は実usageと区別する。個別のIDやパスは戻り値に含めない。
    """
    reconciliation = call.details.get("reconciliation", {})
    upper_bound = reconciliation.get("basis") == "reservation_upper_bound"
    basis = "upper_bound" if upper_bound else "usage"
    if call.cost_nusd is None:
        basis = "unresolved"
    result = {"basis": basis,
              "amount_nusd": call.reserved_nusd if call.cost_nusd is None else call.cost_nusd,
              "response_present": False, "errors": []}
    if upper_bound and (call.cost_nusd != call.reserved_nusd
                        or call.state not in {"retry", "stopped"}):
        result["errors"].append("invalid_upper_bound")
    try:
        envelope = json.loads(Path(call.response_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        if basis == "usage":
            result["errors"].append("missing_settled_response")
        return result
    except (ValueError, UnicodeError):
        result["errors"].append("invalid_saved_response")
        return result
    result["response_present"] = True
    if call.response_hash and digest(envelope) != call.response_hash:
        result["errors"].append("response_hash_mismatch")
    if basis != "usage":
        return result
    try:
        body = json.loads(envelope["body"])
        cost = 0 if call.endpoint.endswith("input_tokens") and envelope["status"] == 200 else (
            usage_cost(body.get("usage")))
    except (ValueError, TypeError, KeyError, AttributeError):
        cost = None
    if cost is None or cost != call.cost_nusd:
        result["errors"].append("cost_mismatch")
    return result
