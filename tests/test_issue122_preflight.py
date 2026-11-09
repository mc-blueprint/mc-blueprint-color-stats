"""本番job作成前に原画像・prepのアクセス不備を検出する。"""

import hashlib
import uuid
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

pytest.importorskip("pwd")

from bench.issue122 import production


@pytest.mark.parametrize("missing", ["raw", "prep"])
def test_all_inputs_must_be_readable_before_analysis(tmp_path, monkeypatch, missing):
    raw = tmp_path / "raw.jpg"
    prep = tmp_path / "prep.jpg"
    raw.write_bytes(b"original")
    prep.write_bytes(b"prepared")
    row = {"asset_id": str(uuid.uuid4()), "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
           "input_path": str(prep), "input_sha256": hashlib.sha256(prep.read_bytes()).hexdigest()}
    session = SimpleNamespace(get=lambda *args: SimpleNamespace(storage_path=str(raw)))
    monkeypatch.setattr(production, "Session", lambda db: nullcontext(session))
    production.check_access(None, [row])
    {"raw": raw, "prep": prep}[missing].unlink()
    with pytest.raises(PermissionError, match="全原画像・prep"):
        production.check_access(None, [row])
