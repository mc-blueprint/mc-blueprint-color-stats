import hashlib
import json

import pytest
from bench.issue114.human_preflight import audit


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    files = {"user-reply-original.md": "問題なし",
             "user-reply-canonical.txt": "全1枚確認済み\n問題なし",
             "review.html": "<html>私有の提示資料</html>",
             "number-map.json": json.dumps({"rows": [
                 {"number": 1, "asset_id": "private-asset", "sha256": "a" * 64}]})}
    for name, content in files.items():
        (root / name).write_text(content, encoding="utf-8")
    keys = {"original_reply_sha256": "user-reply-original.md",
            "human_reply_sha256": "user-reply-canonical.txt",
            "number_map_sha256": "number-map.json", "presentation_sha256": "review.html"}
    summary = {key: hashlib.sha256((root / name).read_bytes()).hexdigest()
               for key, name in keys.items()}
    summary.update(problem_count=0, completion_explicit_in_original=False)
    (root / "human-evaluation-private.json").write_text(json.dumps({
        "summary": summary, "records": [{"asset_id": "private-asset"}]}), encoding="utf-8")
    return root


def test_unpresented_references_remain_held(source, tmp_path, capsys):
    before = {path.name: path.read_bytes() for path in source.iterdir()}
    output = tmp_path / "output"
    audit(source, output)
    result = json.loads((output / "preflight.json").read_text(encoding="utf-8"))
    assert result["human_runs_written"] == 0
    assert result["missing_references"] == 1
    assert result["requires_new_presentation"] is True
    assert result["database_connected"] is False
    assert "private-asset" not in capsys.readouterr().out
    assert {path.name: path.read_bytes() for path in source.iterdir()} == before


@pytest.mark.parametrize("filename", ["user-reply-original.md", "number-map.json", "review.html"])
def test_changed_evidence_stops_before_output(source, tmp_path, filename):
    with (source / filename).open("ab") as stream:
        stream.write(b"modified")
    output = tmp_path / "output"
    with pytest.raises(AssertionError):
        audit(source, output)
    assert not output.exists()
