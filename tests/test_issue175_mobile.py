"""mobileの番号単位容量と原画像byteの維持を検証する。"""

import base64
import hashlib
import io
import os
from pathlib import Path
from uuid import UUID

import pytest
from bench.issue114 import mobile
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from colorstats.review_html import image_tag
from colorstats.schema.models import Asset, RetentionFile
from tests.test_issue114_mobile import synthetic_renderer as synthetic_renderer
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue


def sized_card(number, size, total=1):
    stream = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(stream, format="PNG")
    uri = "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()
    card = f'<article id="n{number}">' + image_tag(uri, "合成", "raw") + '<!-- --></article>'
    header = mobile.page([card], number, number, total).encode()
    return card.replace("<!-- -->", "<!--" + "x" * (size - len(header) + 1) + "-->")


@pytest.mark.parametrize("size", [12_500_001, 25_000_000, 25_000_001, 50_000_000])
def test_単一番号の大きいページを50MBまで受理する(tmp_path, size):
    card = sized_card(1, size)
    files = mobile.write_pages([card], tmp_path)
    assert len(files) == 1 and files[0]["bytes"] == size
    content = (tmp_path / files[0]["file"]).read_text(encoding="utf-8")
    mobile.validate_html(content, [1], limit=mobile._page_limit(1), style=mobile.STYLE)


def test_単一番号でも50MB超は拒否する(tmp_path):
    with pytest.raises(ValueError, match="容量上限"):
        mobile.write_pages([sized_card(1, 50_000_001)], tmp_path)


@pytest.mark.parametrize("large_at", [0, 1, 2])
def test_大きい番号を前後の番号から独立したページに分割する(tmp_path, large_at):
    cards = [sized_card(n, 12_500_001 if n == large_at + 1 else 10_000, total=3)
             for n in range(1, 4)]
    files = mobile.write_pages(cards, tmp_path)
    assert [n for f in files for n in range(f["first"], f["last"] + 1)] == [1, 2, 3]
    large = next(f for f in files if f["first"] <= large_at + 1 <= f["last"])
    assert large["first"] == large["last"] == large_at + 1
    for item in files:
        numbers = range(item["first"], item["last"] + 1)
        limit = mobile._page_limit(len(numbers))
        assert item["bytes"] <= limit
        mobile.validate_html((tmp_path / item["file"]).read_text(encoding="utf-8"),
                             numbers, limit=limit, style=mobile.STYLE)


def test_複数番号に単一番号の50MB上限を適用しない():
    cards = [sized_card(1, 12_500_001, total=2), sized_card(2, 10_000, total=2)]
    content = mobile.page(cards, 1, 2, 2)
    assert 12_500_000 < len(content.encode()) < 25_000_000
    with pytest.raises(ValueError, match="容量上限"):
        mobile.validate_html(content, [1, 2], limit=mobile._page_limit(2), style=mobile.STYLE)


@pytest.mark.parametrize("entry", ["delivery", "reply"])
def test_DB固定値が一致しても複数番号の容量超過を拒否する(
    tmp_path, monkeypatch, synthetic_renderer, entry,
):
    from tests.test_issue114_mobile import UNIT_DB, freeze_delivery, sample

    manifest, mapping, reply = sample(tmp_path)
    render = mobile._render

    def oversized(*args, **kwargs):
        cards, rows, groups = render(*args, **kwargs)
        cards[0] = cards[0].replace("</article>", "<!--" + "x" * 12_500_000 + "--></article>")
        return cards, rows, groups

    monkeypatch.setattr(mobile, "_render", oversized)
    with mobile.Session(UNIT_DB) as session:
        cards, _, groups = oversized(session, None, None, tmp_path, None, False, "comparison")
    content = mobile.page(cards, 1, 2, 2, groups, legend=mobile._legend(cards)).encode()
    assert 12_500_000 < len(content) < 25_000_000
    path = tmp_path / "review-01.html"
    path.write_bytes(content)
    mapping["files"] = [{"file": path.name, "first": 1, "last": 2, "bytes": len(content),
                         "sha256": hashlib.sha256(content).hexdigest()}]
    freeze_delivery(mapping, tmp_path)
    with pytest.raises(ValueError, match="容量上限"):
        if entry == "delivery":
            mobile.validate_delivery(mapping, tmp_path, db=UNIT_DB)
        else:
            mobile.reply_reviews(mapping, manifest, "a" * 64, reply, db=UNIT_DB)


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="隔離DB専用")
def test_大きい原画像の同一番号でDB固定と配信と返信と保持が一致する(
    queue, asset, tmp_path, monkeypatch,
):
    from tests import test_issue173_db as grouped_fixtures

    save = Image.Image.save

    def large_save(image, fp, *args, **kwargs):
        save(image, fp, *args, **kwargs)
        if isinstance(fp, (str, Path)) and Path(fp).name == "acquired.png":
            with Path(fp).open("ab") as stream:
                stream.write(b"\0" * 18_800_000)

    monkeypatch.setattr(Image.Image, "save", large_save)
    data = grouped_fixtures.grouped.__wrapped__(queue, asset, tmp_path, monkeypatch)
    mapping = grouped_fixtures.build(queue, data)
    assert len(mapping["rows"]) == 2 and len(mapping["files"]) == 1
    item = mapping["files"][0]
    assert item["first"] == item["last"] == 1
    assert 25_000_000 < item["bytes"] <= mobile.SINGLE_LIMIT
    with Session(queue.engine) as session:
        original = session.get(Asset, UUID(mapping["rows"][0]["asset_id"]))
        raw_path = Path(original.storage_path)
        uri = mobile.file_uri(raw_path)
        assert base64.b64decode(uri.split(",", 1)[1]) == raw_path.read_bytes()
        actual = set(session.scalars(select(RetentionFile.asset_id).where(
            RetentionFile.path == str(data.human / item["file"]))))
        assert actual == {UUID(r["asset_id"]) for r in mapping["rows"]}
    assert uri in (data.human / item["file"]).read_text(encoding="utf-8")
    rows, _ = mobile.validate_delivery(mapping, data.human, db=queue.engine)
    assert len(rows) == 2
    delivery = tmp_path / "delivery"
    assert mobile.share(queue.engine, data.human, delivery) == mapping
    converted = mobile.reply_reviews(
        mapping, delivery / "review-manifest.json", data.manifest["decisions_sha256"],
        "全1枚確認済み\n問題なし", db=queue.engine,
    )
    assert len(converted["rows"]) == 2
