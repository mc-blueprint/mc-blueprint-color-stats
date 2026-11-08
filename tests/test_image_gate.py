import ast
import io
import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin

from colorstats import image_gate as gate
from colorstats.api_budget import Ledger, retry_delay, usage_cost


@pytest.mark.parametrize("value", ["0", "5", "invalid"])
def test_同時送信数の範囲外設定を拒否する(monkeypatch, value):
    monkeypatch.setenv("COLORSTATS_IMAGE_GATE_CONCURRENCY", value)
    with pytest.raises(ValueError):
        Ledger(None, None, None)


def test_停止閾値とtimeoutの既定値および設定値を確認する(monkeypatch):
    assert Ledger(None, None, None).policy == {
        "unknown_streak": 3, "unknown_total": 30, "rate_limit_streak": 2, "timeout_seconds": 120,
    }
    monkeypatch.setenv("COLORSTATS_IMAGE_GATE_UNKNOWN_STREAK", "4")
    monkeypatch.setenv("COLORSTATS_IMAGE_GATE_UNKNOWN_TOTAL", "40")
    monkeypatch.setenv("COLORSTATS_IMAGE_GATE_TIMEOUT", "180")
    assert Ledger(None, None, None).policy["unknown_total"] == 40
    assert Ledger(None, None, None).policy["unknown_streak"] == 4
    assert Ledger(None, None, None).policy["timeout_seconds"] == 180


@pytest.mark.parametrize("seconds", [120, 180])
def test_HTTP要求は設定timeoutで一度だけ送る(monkeypatch, seconds):
    from unittest.mock import MagicMock, Mock

    from colorstats import api_budget

    monkeypatch.setenv("COLORSTATS_IMAGE_GATE_TIMEOUT", str(seconds))
    response = MagicMock(code=200, headers={})
    response.read.return_value = b"{}"
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr(api_budget, "build_opener", lambda *args: opener)
    assert api_budget.request("responses", {}, "fixture")["status"] == 200
    assert opener.open.call_count == 1
    assert opener.open.call_args.kwargs["timeout"] == seconds


def verdict(**changes):
    return {"target": True, "subject": "building", "real_people": "absent",
            "interior": False, "black_and_white": False, "dark": False, "aerial_view": False,
            "reason_codes": ["building_detail"], **changes}


def response(**changes):
    return {"id": "resp_fixture", "model": gate.MODEL, "status": "completed",
            "reasoning": {"effort": "low"},
            "usage": {"input_tokens": 4000, "output_tokens": 100,
                      "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0}},
            "output": [{"type": "message", "content": [
                {"type": "output_text", "text": json.dumps(verdict())},
            ]}], **changes}


@pytest.mark.parametrize(("changes", "expected"), [
    ({}, "accepted"), ({"interior": True}, "accepted"),
    ({"black_and_white": True}, "rejected"),
    ({"subject": "other", "target": False}, "rejected"),
    ({"real_people": "present"}, "pending"),
    ({"real_people": "uncertain"}, "pending"),
    ({"dark": True}, "pending"), ({"dark": None}, "pending"),
    ({"aerial_view": True}, "pending"), ({"aerial_view": None}, "pending"),
    ({"subject": "mixed"}, "pending"), ({"subject": "unknown"}, "pending"),
    ({"target": None}, "pending"), ({"interior": None}, "pending"),
    ({"black_and_white": None}, "pending"), ({"reason_codes": []}, "pending"),
    ({"reason_codes": ["uncertain"]}, "pending"),
    ({"reason_codes": ["sheet_music"]}, "pending"),
    ({"reason_codes": ["not_a_code"]}, "pending"),
    ({"extra": "ignored?"}, "pending"), ({"target": "true"}, "pending"),
])
def test_採否と不明は固定policyで決まる(changes, expected):
    result = gate.decision(verdict(**changes))
    assert result["decision"] == expected
    assert (result["analysis_domain"] is not None) == (expected == "accepted")


def test_確定主体との矛盾は検索意図に優先して保留する():
    assert gate.decision(verdict(), "real_terrain")["reason"] == "subject_conflict"
    assert gate.decision(verdict(subject="terrain"))["analysis_domain"] == "real_terrain"


def test_上空属性は必須で他の除外理由があっても保留する():
    old = verdict()
    del old["aerial_view"]
    assert gate.decision(old)["reason"] == "invalid_schema"
    for aerial in (True, None):
        assert gate.decision(verdict(aerial_view=aerial, black_and_white=True,
                                     target=False))["decision"] == "pending"


@pytest.mark.parametrize("changes", [
    {"model": "gpt-6.1-sol"}, {"model": None}, {"status": "incomplete"},
    {"output": [{"type": "message", "content": [{"type": "refusal"}]}]},
    {"output": []}, {"output": [{"type": "function_call"}]},
    {"output": None}, {"output": ["invalid"]},
    {"reasoning": {"effort": "high"}},
    {"reasoning": {}}, {"reasoning": None},
    {"output": [{"type": "message", "content": [{"type": "output_text", "text": "{"}]}]},
])
def test_別modelや拒否や不完全応答は採用しない(changes):
    result, error = gate.parse_response(response(**changes))
    assert result is None
    assert error


def test_送信画像はmetadataを落として1024px以下にする():
    image = Image.new("RGB", (2000, 1000), "red")
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("secret", "source title")
    source = io.BytesIO()
    image.save(source, format="PNG", pnginfo=metadata)
    clean = gate.normalize(source.getvalue())
    with Image.open(io.BytesIO(clean)) as result:
        assert result.size == (1024, 512)
        assert result.info == {}
    assert clean == gate.normalize(source.getvalue())


def test_費用は整数でcacheとreasoningを含む全出力を計上する():
    assert usage_cost({"input_tokens": 100, "output_tokens": 50,
                       "input_tokens_details": {"cached_tokens": 10, "cache_write_tokens": 20}}
                      ) == 70 * 100 + 10 * 10 + 20 * 125 + 50 * 500
    assert usage_cost({"input_tokens": 10}) is None
    assert usage_cost({"input_tokens": 10, "output_tokens": 1,
                       "input_tokens_details": {"cached_tokens": 0}}) is None
    assert usage_cost({"input_tokens": 10, "output_tokens": 1,
                       "input_tokens_details": {"cached_tokens": 11}}) is None
    assert usage_cost({"input_tokens": 10, "output_tokens": 1,
                       "input_tokens_details": {"new_charge": 1}}) is None


def test_架空usageのcache書込みを30分の実単価で精算する():
    usages = [(2000, 1000, 200), (3000, 2000, 100), (1000, 0, 300)]
    assert sum(usage_cost({"input_tokens": inputs, "output_tokens": outputs,
                           "input_tokens_details": {"cached_tokens": 0,
                                                    "cache_write_tokens": writes}})
               for inputs, writes, outputs in usages) == 975_000


def test_費用fixtureは丸めた架空値だけを使う():
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    groups = [ast.literal_eval(node.value) for node in ast.walk(tree)
              if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == "usages"
                      for target in node.targets)]
    assert groups
    if any(value % 100 for group in groups for row in group for value in row):
        raise AssertionError("画像単位の実測値を使わず、100 token単位の架空値に限定します")


@pytest.mark.parametrize("breakdown,expected", [
    ({"ttl_30m_tokens": 20, "ttl_12h_tokens": 0}, 2500),
    ({"ttl_30m_tokens": 0, "ttl_12h_tokens": 20}, 5000),
    ({"ttl_30m_tokens": 10, "ttl_12h_tokens": 10}, 3750),
    ({"ttl_30m_tokens": 10, "ttl_12h_tokens": 9}, None),
    ({"ttl_30m_tokens": -1, "ttl_12h_tokens": 21}, None),
])
def test_TTL別書込み内訳の精算と合計不一致を確認する(breakdown, expected):
    result = usage_cost({"input_tokens": 20, "output_tokens": 0,
                         "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 20,
                                                  "cache_write_tokens_details": breakdown}})
    assert result == expected


def test_書込み内訳省略時は明示TTLを使い未知のTTLを精算しない():
    usage = {"input_tokens": 20, "output_tokens": 0,
             "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 20}}
    assert usage_cost(usage, cache_ttl="12h") == 5000
    assert usage_cost(usage, cache_ttl="unknown") is None


def test_RetryAfterは秒数とHTTP日付を扱う():
    assert retry_delay("120") == 120
    assert 118 <= retry_delay(format_datetime(datetime.now(UTC) + timedelta(seconds=120))) <= 120
    assert retry_delay(None) == 30


def test_品質reviewへAPI型を渡さない():
    from types import SimpleNamespace

    from colorstats.collect.quality import prepare

    with pytest.raises(ValueError, match="kind"):
        prepare(SimpleNamespace(payload={"kind": "image_gate"}))
