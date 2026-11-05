import hashlib
import json
from pathlib import Path

import duckdb
from PIL import Image


def test_旧14組なしで固定100件と通信予算を生成できる(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "bench/issue90"))
    from existing import freeze

    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    root = tmp_path / "comparison"
    root.mkdir()
    files, assets = [], []
    for index in range(100):
        path = tmp_path / f"{index}.png"
        Image.new("RGB", (1 if index % 50 == 0 else 1281, 1), (index, 0, 0)).save(path)
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append({"source": str(path), "sha256": sha})
        data = {
            "search_provider": "wikimedia_commons", "collected_title": f"File:{index}.png",
            "quality": {"metadata": {
                "url": f"https://example.test/{index}.png",
                "descriptionurl": f"https://example.test/File:{index}.png",
            }},
        }
        assets.append((str(index), sha, "real_building" if index < 50 else "real_terrain",
                       json.dumps(data), True))
    with duckdb.connect() as db:
        db.execute("CREATE TABLE assets(id VARCHAR, sha256 VARCHAR, domain VARCHAR, "
                   "data VARCHAR, rights_eligible BOOLEAN)")
        db.executemany("INSERT INTO assets VALUES (?, ?, ?, ?, ?)", assets)
        db.table("assets").write_parquet(str(snapshot / "assets.parquet"))
    manifest = tmp_path / "raw-manifest.json"
    manifest.write_text(json.dumps({"files": files}))
    freeze(root, snapshot, manifest)
    selected = json.loads((root / "manifest.json").read_text())
    assert len(selected) == len({row["sha256"] for row in selected}) == 100
    assert all("cached_thumbnail" not in row for row in selected)
    assert json.loads((root / "budget.json").read_text())["limits"] == {
        "api": 10, "original": 0, "thumbnail": 100,
    }
