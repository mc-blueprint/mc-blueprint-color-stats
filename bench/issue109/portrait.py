"""#90固定100件の縦長画像を読み取り、新しい1280角内縮小と対応比較する。"""

import copy
import hashlib
import json
import shutil
import sys
import time
from collections import Counter
from functools import lru_cache
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from PIL import Image

from colorstats.analyze import segment
from colorstats.collect.commons import ENDPOINT, CommonsAdapter
from colorstats.collect.http import MeasurementLimit
from colorstats.collect.policy import load_policy


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    root = Path(sys.argv[1])
    baseline = Path("/mnt/data/derived/issue90-20261105/existing100")
    sys.path.insert(0, "/mnt/data/derived/issue90-20261105/code-resume/bench/issue90")
    from compare import analyze

    resuming = (root / "selection.json").exists()
    rows = (json.loads((root / "manifest.json").read_text()) if resuming else [
        copy.deepcopy(row) for row in json.loads((baseline / "manifest.json").read_text())
        if row["height"] > row["width"]
    ])
    assert 0 < len(rows) <= 30
    budget = (json.loads((root / "budget.json").read_text()) if resuming else {
        "limits": {"api": 5, "thumbnail": 30, "original": 0},
        "used": {"api": 0, "thumbnail": 0, "original": 0},
    })
    save(root / "budget.json", budget)
    original_hashes = {}
    for row in rows:
        original = row["arms"]["original-1.0"]
        with Path(original["path"]).open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        assert digest == original["sha256"] == row["sha256"]
        original_hashes[original["path"]] = digest
        if not resuming:
            row.pop("comparison", None)
            row.pop("analysis_error", None)
            row["arms"] = {"original-1.0": original}
            row["status"] = "selected"
            source = baseline / f"analysis-{row['index']:03d}-original"
            shutil.copytree(source, root / source.name)
    if not resuming:
        save(root / "selection.json", {
            "source": str(baseline / "manifest.json"),
            "rule": "#90固定100件からheight > widthの全件を元index順に選定。除外・追加選定なし。",
            "count": len(rows), "indices": [row["index"] for row in rows],
            "original_sha256": original_hashes,
            "source_sha256": hashlib.sha256((baseline / "manifest.json").read_bytes()).hexdigest(),
        })
    events = json.loads((root / "events.json").read_text()) if resuming else []
    adapter = CommonsAdapter(load_policy(root / "source_policy.yaml", "wikimedia_commons"))

    def observe(event, value=1):
        if event in {"api_request", "request"}:
            key = "api" if event == "api_request" else "thumbnail"
            if budget["used"][key] >= budget["limits"][key]:
                raise MeasurementLimit(key)
            budget["used"][key] += 1
            save(root / "budget.json", budget)
        events.append({"event": event, "value": value})

    adapter.observer = observe
    try:
        parameters = {
            "action": "query", "format": "json", "formatversion": 2, "maxlag": 5,
            "prop": "imageinfo", "iiprop": "url|size|mime|thumbmime|timestamp|sha1",
            "iiurlwidth": 1280, "iiurlheight": 1280,
            "titles": "|".join(row["candidate"]["title"] for row in rows),
        }
        if (root / "imageinfo.json").exists():
            response = json.loads((root / "imageinfo.json").read_text())
        else:
            response = adapter._get(ENDPOINT + "?" + urlencode(parameters))
            save(root / "imageinfo.json", response)
        pages = {page["title"].replace("_", " "): page
                 for page in response.get("query", {}).get("pages", [])}
        for row in rows:
            if "thumbnail-1.0" in row["arms"]:
                continue
            info = pages[row["candidate"]["title"].replace("_", " ")]["imageinfo"][0]
            variant = row["arms"]["original-1.0"]["variant"]
            if info.get("sha1") != variant["original"]["sha1"]:
                row["status"] = "original_revision_changed"
                continue
            if max(row["width"], row["height"]) <= 1280:
                row["status"] = "thumbnail_not_smaller"
                continue
            if not all(info.get(key) for key in (
                "thumburl", "thumbwidth", "thumbheight", "thumbmime",
            )):
                row["status"] = "thumbnail_missing"
                continue
            target = root / f"{row['index']:03d}-thumbnail.image"
            started = time.monotonic()
            if not target.exists():
                adapter._get(info["thumburl"], target=target)
                adapter.finish()
            with Image.open(target) as image:
                width, height, mime = image.width, image.height, Image.MIME[image.format]
            assert max(width, height) >= 1280
            rendition = {**variant, "variant": "thumbnail", "requested_width": 1280,
                         "requested_height": 1280, "width": width, "height": height, "mime": mime}
            row["arms"]["thumbnail-1.0"] = {
                "status": "ok", "path": str(target), "bytes": target.stat().st_size,
                "width": width, "height": height, "mime": mime, "variant": rendition,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "events": [], "elapsed_seconds": time.monotonic() - started,
                "acquisition": "new_long_edge_thumbnail",
            }
            row["status"] = "acquired"
            save(root / "manifest.json", rows)
    finally:
        adapter.finish()
        save(root / "events.json", events)
        save(root / "manifest.json", rows)
    with patch.object(segment, "_hash", lru_cache(maxsize=None)(segment._hash)):
        analyze(root, Path("/mnt/data/derived/issue66-workers-20261104/models"), "analysis")
    rows = json.loads((root / "manifest.json").read_text())
    for path, digest in original_hashes.items():
        with Path(path).open("rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == digest
    pairs = [row["comparison"] for row in rows if "comparison" in row]
    masks = [mask for pair in pairs for mask in pair["mask_agreement"].values()
             if mask["group"] == "major"]
    intersection, union = (sum(mask[key] for mask in masks) for key in ("intersection", "union"))
    distance = (sum(pair["dominant_oklab_distance"] for pair in pairs) / len(pairs)
                if pairs else None)
    agreement = intersection / union if union else None
    result = {
        "selected": len(rows), "evaluated": len(pairs), "unevaluated": len(rows) - len(pairs),
        "status": dict(Counter(row["status"] for row in rows)), "budget": budget,
        "dominant_oklab_mean": distance, "major_agreement": agreement,
        "intersection": intersection, "union": union,
        "passed": len(pairs) == len(rows) and distance <= 0.02 and agreement >= 0.85,
        "originals_unchanged": len(original_hashes),
        "analysis_errors": [row["analysis_error"] for row in rows if "analysis_error" in row],
        "received_long_edges": sorted({max(row["arms"]["thumbnail-1.0"][key]
                                           for key in ("width", "height"))
                                       for row in rows if "thumbnail-1.0" in row["arms"]}),
    }
    save(root / "summary.json", result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
