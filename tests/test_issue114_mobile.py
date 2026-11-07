import base64
import copy
import io
import json
import re

import pytest
from bench.issue114.mobile import jpeg, overlay, reply_reviews, write_pages
from bench.issue114.privacy import digest
from PIL import Image


def sample(tmp_path):
    rows = [{"asset_id": "accepted", "decision": "accepted", "subject": "building"},
            {"asset_id": "pending", "decision": "pending", "subject": None}]
    manifest = tmp_path / "review-manifest.json"
    manifest.write_text(json.dumps({"required_ids": ["accepted", "pending"], "rows": rows}))
    mapping = {"format": "issue114-mobile-v1", "decisions_sha256": "a" * 64,
               "review_manifest_sha256": digest(manifest),
               "rows": [row | {"number": i} for i, row in enumerate(rows, 1)]}
    reply = {"all_reviewed": True, "reply_text": "全2枚確認済み、問題なし", "problems": []}
    return manifest, mapping, reply


def test_会話確認は提示画像だけに限定し保留を採用へ昇格しない(tmp_path):
    manifest, mapping, reply = sample(tmp_path)
    data = reply_reviews(mapping, manifest, "a" * 64, reply)
    assert data["reviewer"] == "ユーザー" and data["confirm_no_errors"]
    assert [row["decision"] for row in data["rows"]] == ["same", "same"]
    assert data["rows"][1]["subject"] is None
    reply.update(reply_text="全2枚確認済み。1は人物見落とし",
                 problems=[{"number": 1, "reason": "人物見落とし"}])
    data = reply_reviews(mapping, manifest, "a" * 64, reply)
    assert not data["confirm_no_errors"]
    assert data["rows"][0]["decision"] == "pending" and data["rows"][0]["error_found"]
    assert data["rows"][0]["note"] == "人物見落とし"


@pytest.mark.parametrize("problems", [
    [{"number": 0, "reason": "人物"}], [{"number": 3, "reason": "人物"}],
    [{"number": 1, "reason": " "}], [{"number": True, "reason": "人物"}],
    [{"number": 1, "reason": "人物"}, {"number": 1, "reason": "主体"}],
])
def test_番号や理由の不備は確認記録へ変換しない(tmp_path, problems):
    manifest, mapping, reply = sample(tmp_path)
    with pytest.raises(ValueError):
        reply_reviews(mapping, manifest, "a" * 64, reply | {"problems": problems})


def test_未完了返信や変更された番号表を拒否する(tmp_path):
    manifest, mapping, reply = sample(tmp_path)
    with pytest.raises(ValueError, match="確認済み"):
        reply_reviews(mapping, manifest, "a" * 64, reply | {"all_reviewed": False})
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


def test_JPEGは端末向け寸法と人物主体の色を保つ(tmp_path):
    image = Image.new("RGB", (1600, 1000), "white")
    person = tmp_path / "person.png"
    subject = tmp_path / "building.png"
    mask = Image.new("L", image.size)
    mask.paste(255, (0, 0, 800, 1000))
    mask.save(subject)
    mask = Image.new("L", image.size)
    mask.paste(255, (0, 0, 100, 100))
    mask.save(person)
    result = overlay(image, [("wall", subject)], person, {"wall"}, set())
    assert result.getpixel((50, 50))[0] > result.getpixel((50, 50))[1]
    assert result.getpixel((500, 500))[1] > result.getpixel((500, 500))[0]
    assert result.getpixel((1200, 500)) == (255, 255, 255)
    with Image.open(io.BytesIO(base64.b64decode(jpeg(result).split(",")[1]))) as decoded:
        assert decoded.format == "JPEG" and decoded.size == (800, 500)


def test_HTML分割は実byte上限と連番を守り外部参照を含まない(tmp_path):
    cards = [f'<article id="n{i}">番号{i}<img src="{jpeg(Image.new("RGB", (20, 20)))}"></article>'
             for i in range(1, 7)]
    files = write_pages(cards, tmp_path, limit=3500)
    assert len(files) == 2 and abs(files[0]["bytes"] - files[1]["bytes"]) < 100
    numbers = []
    for item in files:
        path = tmp_path / item["file"]
        assert path.stat().st_size <= 3500
        content = path.read_text()
        numbers.extend(map(int, re.findall(r'id="n(\d+)"', content)))
        assert "http:" not in content and "https:" not in content
        assert all(src.startswith("data:image/jpeg;base64,")
                   for src in re.findall('src="([^"]+)"', content))
    assert numbers == list(range(1, 7))
