import base64
import copy
import io
import json
import re
from contextlib import nullcontext
from types import SimpleNamespace

import numpy as np
import pytest
from bench.issue114 import mobile
from bench.issue114.mobile import (
    apply_privacy_reply,
    jpeg,
    mask_uri,
    outline_uri,
    parse_chat_reply,
    reply_reviews,
    write_pages,
)
from bench.issue114.privacy import digest
from PIL import Image

from colorstats import privacy_review, retention


def sample(tmp_path):
    rows = [{"asset_id": "accepted", "decision": "accepted", "subject": "building"},
            {"asset_id": "pending", "decision": "pending", "subject": None}]
    manifest = tmp_path / "review-manifest.json"
    manifest.write_text(json.dumps({"required_ids": ["accepted", "pending"], "rows": rows}))
    mapping = {"format": "issue114-mobile-v1", "decisions_sha256": "a" * 64,
               "review_manifest_sha256": digest(manifest),
               "rows": [row | {"number": i} for i, row in enumerate(rows, 1)]}
    reply = "全2枚確認済み\n問題なし"
    return manifest, mapping, reply


@pytest.mark.parametrize("reply", [
    {"all_reviewed": True, "reply_text": "未確認", "problems": []},
    {"all_reviewed": True, "reply_text": "全2枚確認済み\n問題なし", "problems": []},
    {"all_reviewed": True, "reply_text": "全2枚確認済み\n1: 人物", "problems": []},
])
def test_辞書入力では定型解析を迂回できない(tmp_path, reply):
    manifest, mapping, _ = sample(tmp_path)
    with pytest.raises(ValueError, match="肯定形返信"):
        reply_reviews(mapping, manifest, "a" * 64, reply)


def test_会話確認は問題番号を保留にし既存保留を採用へ昇格しない(tmp_path):
    manifest, mapping, reply = sample(tmp_path)
    data = reply_reviews(mapping, manifest, "a" * 64, reply)
    assert data["reviewer"] == "ユーザー" and data["confirm_no_errors"]
    assert [row["decision"] for row in data["rows"]] == ["same", "same"]
    assert data["rows"][1]["subject"] is None
    reply = "全2枚確認済み\n1: 人物見落とし"
    data = reply_reviews(mapping, manifest, "a" * 64, reply)
    assert not data["confirm_no_errors"]
    assert data["rows"][0]["decision"] == "pending" and data["rows"][0]["error_found"]
    assert data["rows"][0]["note"] == "人物見落とし"


def test_番号返信はproblemを保留し他画像をprivacy_review_writeで確認する(monkeypatch):
    calls = []

    def record_hold(*args, **kwargs):
        calls.append(("hold", args, kwargs))
        return "held-run"

    def write(*args, **kwargs):
        calls.append(("write", args, kwargs))
        return "confirmed-run"

    def old_writer(*args, **kwargs):
        raise AssertionError("旧privacy writerを呼び出しました")

    monkeypatch.setattr(privacy_review, "record_hold", record_hold)
    monkeypatch.setattr(privacy_review, "write", write)
    monkeypatch.setattr(retention, "review_privacy", old_writer)
    data = {"reviewer": "ユーザー", "rows": [
        {"asset_id": "flagged", "error_found": True, "note": "人物の見落とし",
         "privacy_review_run_id": "privacy-1", "presented_source_sha256": "a" * 64},
        {"asset_id": "clear", "error_found": False, "note": "問題なし",
         "privacy_review_run_id": "00000000-0000-0000-0000-000000000002",
         "presented_source_sha256": "b" * 64,
         "image_gate_run_id": "gate-2", "region_policy_run_id": "region-2",
         "confirmed_real_people": "absent"},
    ]}

    original = SimpleNamespace(parameters={
        "evidence": {"real_people": "present", "human_hold": True},
    })
    session = SimpleNamespace(get=lambda *args: original)
    queue = SimpleNamespace(_transaction=lambda: nullcontext(session))
    result = apply_privacy_reply(queue, data)

    assert [call[0] for call in calls] == ["hold", "write"]
    assert calls[0][1][1:3] == ("flagged", "privacy-1")
    assert calls[0][2]["note"] == "人物の見落とし"
    assert calls[1][1][1:4] == ("clear", "gate-2", "region-2")
    assert calls[1][2]["input_run_id"] == "00000000-0000-0000-0000-000000000002"
    assert calls[1][2]["real_people"] == "present" and calls[1][2]["hold"]
    assert [row["recorded_privacy_review_run_id"] for row in result["rows"]] == [
        "held-run", "confirmed-run",
    ]
    assert not hasattr(mobile, "import_reviews")


@pytest.mark.parametrize("body", [
    "0: 人物", "3: 人物", "1: ", "True: 人物", "1: 人物\n1: 主体", "1", "人物",
])
def test_番号や理由の不備は拒否する(tmp_path, body):
    manifest, mapping, _ = sample(tmp_path)
    with pytest.raises(ValueError):
        reply_reviews(mapping, manifest, "a" * 64, "全2枚確認済み\n" + body)


def test_未完了返信や変更された番号表を拒否する(tmp_path):
    manifest, mapping, reply = sample(tmp_path)
    with pytest.raises(ValueError, match="確認済み"):
        reply_reviews(mapping, manifest, "a" * 64, "全2枚未確認\n問題なし")
    altered = copy.deepcopy(mapping)
    altered["rows"][0]["subject"] = "terrain"
    with pytest.raises(ValueError, match="自動判定"):
        reply_reviews(altered, manifest, "a" * 64, reply)
    altered = copy.deepcopy(mapping)
    altered["rows"].reverse()
    for number, row in enumerate(altered["rows"], 1):
        row["number"] = number
    with pytest.raises(ValueError, match="対象・連番"):
        reply_reviews(altered, manifest, "a" * 64, reply)
    with pytest.raises(ValueError, match="一致"):
        reply_reviews(mapping, manifest, "b" * 64, reply)
    manifest.write_text(manifest.read_text() + " ")
    with pytest.raises(ValueError, match="固定した閲覧対象"):
        reply_reviews(mapping, manifest, "a" * 64, reply)


@pytest.mark.parametrize("reply,expected", [
    ("全138枚確認済み\n問題なし", []),
    ("全１３８枚確認済み。\r\n問題なし\r\n", []),
    ("\n全138枚確認済み\n\n問題なし\n\n", []),
    ("全138枚確認済み\n7: 人物が 2 人写っている",
     [{"number": 7, "reason": "人物が 2 人写っている"}]),
    ("全138枚確認済み\n7: 人物見落とし。右端に人物がいます",
     [{"number": 7, "reason": "人物見落とし。右端に人物がいます"}]),
    ("全138枚確認済み\n7: 人物maskは問題ないが主体が違う",
     [{"number": 7, "reason": "人物maskは問題ないが主体が違う"}]),
    ("全138枚確認済み\n７：番号 7、85 を比較。人物は未確認",
     [{"number": 7, "reason": "番号 7、85 を比較。人物は未確認"}]),
    ("全138枚確認済み。\r\n７： 人物見落とし。右端に人物がいます\r\n\r\n８５: 主体違い\r\n",
     [{"number": 7, "reason": "人物見落とし。右端に人物がいます"},
      {"number": 85, "reason": "主体違い"}]),
])
def test_定型返信は行頭番号だけを読み理由を保持する(reply, expected):
    parsed = parse_chat_reply(reply, 138)
    assert parsed == {"all_reviewed": True, "reply_text": reply, "problems": expected}


@pytest.mark.parametrize("reply", [
    "", "\n\n", "全138枚確認済み", "全138枚確認済み\n\n",
    "全137枚確認済み\n問題なし", "全138枚未確認\n問題なし",
    "全138枚確認済みではない\n問題なし", "前置き全138枚確認済み\n問題なし",
    "全138枚確認済み\n7: 人物\n７：主体", "全138枚確認済み\n0: 人物",
    "全138枚確認済み\n139: 主体", "全138枚確認済み\n7:",
    "全138枚確認済み\n7:  \n", "全138枚確認済み\n7 人物",
    "全138枚確認済み\n番号 7: 人物", "全138枚確認済み\n7: 人物\n右端に人物がいます",
    "全138枚確認済み\n問題なし\n7: 人物", "全138枚確認済み\n7: 人物\n問題なし",
    "全138枚確認済み\n問題なし\n問題なし", "全138枚確認済み\n問題なし\n補足",
    "全138枚確認済み。問題なし", "全138枚確認済み。問題あり：7 人物",
    "全138枚確認済み\n問題なし。", "全138枚確認済み\n問題あり：7 人物",
])
def test_定型に合わない返信や重複範囲外理由なしを拒否する(reply):
    with pytest.raises(ValueError):
        parse_chat_reply(reply, 138)


@pytest.mark.parametrize("reply", ["全2枚確認済み\n問題なし\n",
                                   "全２枚確認済み。\r\n１：人物見落とし"])
def test_正しい返信もmanifest変更時には拒否する(tmp_path, reply):
    manifest, mapping, _ = sample(tmp_path)
    manifest.write_text(manifest.read_text() + "\n")
    with pytest.raises(ValueError, match="固定した閲覧対象"):
        reply_reviews(mapping, manifest, "a" * 64, reply)


def test_複数画像の番号表へ各自のprivacy_runを保持する():
    decisions = {
        "asset-1": {"selection": {"image_gate_run_id": "gate-1",
                                   "privacy_review_run_id": "privacy-1"}},
        "asset-2": {"selection": {"image_gate_run_id": "gate-2",
                                   "privacy_review_run_id": "privacy-2"}},
    }
    rows = [
        mobile._review_references(
            mobile._selection_for(decisions, "asset-1"),
            {"run_id": "gate-1", "source_sha256": "a" * 64}, "region-1", "absent",
        ),
        mobile._review_references(
            mobile._selection_for(decisions, "asset-2"),
            {"run_id": "gate-2", "source_sha256": "b" * 64}, "region-2", "uncertain",
        ),
    ]
    assert [row["privacy_review_run_id"] for row in rows] == ["privacy-1", "privacy-2"]
    assert [row["presented_source_sha256"] for row in rows] == ["a" * 64, "b" * 64]


def test_画像とmaskは別表示で元座標を保つ():
    image = Image.new("RGB", (1600, 1000), "white")
    mask = np.zeros((1000, 1600), dtype=bool)
    mask[:100, :100] = True
    mask_data = mask_uri(mask, image.size)
    outline_data = outline_uri(mask, image.size, pattern="dash")
    with Image.open(io.BytesIO(base64.b64decode(jpeg(image).split(",")[1]))) as decoded:
        assert decoded.format == "JPEG" and decoded.size == (800, 500)
    with Image.open(io.BytesIO(base64.b64decode(mask_data.split(",")[1]))) as decoded:
        assert decoded.format == "PNG" and decoded.size == image.size
        assert decoded.getpixel((50, 50)) == 255 and decoded.getpixel((500, 500)) == 0
    with Image.open(io.BytesIO(base64.b64decode(outline_data.split(",")[1]))) as decoded:
        assert decoded.format == "PNG" and decoded.size == image.size


def test_HTML容量と連番を守り外部画像を参照しない(tmp_path):
    cards = [f'<article id="n{i}">番号{i}<img src="{jpeg(Image.new("RGB", (20, 20)))}"></article>'
             for i in range(1, 7)]
    files = write_pages(cards, tmp_path, limit=3500,
                        group_counts={"population": 20, "random": 4, "challenge": 2})
    assert len(files) == 2 and abs(files[0]["bytes"] - files[1]["bytes"]) < 100
    numbers = []
    for item in files:
        path = tmp_path / item["file"]
        assert path.stat().st_size <= 3500
        content = path.read_text()
        assert "対象母数：20枚" in content and "固定無作為群：4枚" in content
        numbers.extend(map(int, re.findall(r'id="n(\d+)"', content)))
        assert "http:" not in content and "https:" not in content
        sources = re.findall('src="([^"]+)"', content)
        assert all(src.startswith("data:image/jpeg;base64,") for src in sources)
        for source in sources:
            data = base64.b64decode(source.split(",", 1)[1], validate=True)
            with Image.open(io.BytesIO(data)) as decoded:
                decoded.verify()
    assert numbers == list(range(1, 7))
