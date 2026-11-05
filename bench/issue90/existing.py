"""#74の固定snapshotと既存原本から100件を選び、縮小だけを追加取得する。"""

import argparse
import copy
import hashlib
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

import duckdb
from compare import save
from PIL import Image

from colorstats.collect.commons import ENDPOINT, CommonsAdapter
from colorstats.collect.http import MeasurementLimit
from colorstats.collect.policy import load_policy


def order(row):
    return hashlib.sha256(("issue90-existing-v1:" + row["sha256"]).encode()).hexdigest()


def freeze(root, snapshot, raw_manifest):
    if (root / "selection.json").exists():
        raise FileExistsError("固定選定を上書きしません")
    paths = {}
    for record in json.loads(raw_manifest.read_text())["files"]:
        path = Path(record["source"])
        if path.is_file():
            paths[record["sha256"]] = min(str(path), paths.get(record["sha256"], str(path)))
    with duckdb.connect(config={"threads": 1}) as db:
        db.read_parquet(str(snapshot / "assets.parquet")).create_view("assets")
        rows = db.execute(
            "SELECT id, sha256, domain, data FROM assets WHERE rights_eligible ORDER BY id",
        ).fetchall()
    representatives = {}
    for identifier, sha, domain, raw in rows:
        data = json.loads(raw)
        if (data["search_provider"] == "wikimedia_commons" and sha in paths
                and domain in {"real_building", "real_terrain"}):
            representatives.setdefault(sha, {
                "asset_id": identifier, "sha256": sha, "domain": domain,
                "data": data, "path": paths[sha],
            })
    pool, excluded = [], []
    for row in sorted(representatives.values(), key=order):
        try:
            with Image.open(row["path"]) as image:
                row.update(width=image.width, height=image.height, mime=Image.MIME[image.format])
        except Image.DecompressionBombError:
            excluded.append({"asset_id": row["asset_id"], "sha256": row["sha256"],
                             "reason": "pillow_decompression_bomb_limit"})
            continue
        row["orientation"] = "portrait" if row["height"] > row["width"] else "landscape"
        pool.append(row)
    selected = []
    for domain in ("real_building", "real_terrain"):
        candidates = [row for row in pool if row["domain"] == domain]
        small = next(row for row in candidates if row["width"] <= 1280)
        chosen = [small]
        for orientation in ("portrait", "landscape"):
            count = 25 - int(small["orientation"] == orientation)
            chosen.extend([row for row in candidates if row["width"] > 1280
                           and row["orientation"] == orientation][:count])
        chosen_sha = {row["sha256"] for row in chosen}
        chosen.extend([row for row in candidates if row["width"] > 1280
                       and row["sha256"] not in chosen_sha][:50 - len(chosen)])
        selected.extend(chosen)
    assert len(selected) == len({row["sha256"] for row in selected}) == 100
    selected.sort(key=lambda row: (row["domain"], row["orientation"], order(row)))
    old = json.loads((root.parent / "previous14/manifest.json").read_text())
    cache = {row["arms"]["original-1.0"]["sha256"]: row for row in old
             if "comparison" in row}
    manifest = []
    for index, row in enumerate(selected):
        started = time.monotonic()
        with Path(row["path"]).open("rb") as stream:
            sha = hashlib.file_digest(stream, "sha256").hexdigest()
        with Path(row["path"]).open("rb") as stream:
            sha1 = hashlib.file_digest(stream, "sha1").hexdigest()
        assert sha == row["sha256"]
        data = row.pop("data")
        metadata = data["quality"]["metadata"]
        original = {"url": metadata["url"], "width": row["width"], "height": row["height"],
                    "mime": row["mime"], "sha1": sha1, "sha256": sha}
        rendition = {"provider": "wikimedia_commons", "native_id": None, "revision": None,
                     "variant": "original", "original": original}
        candidate = {
            "title": data["collected_title"], "source_url": metadata["descriptionurl"],
            "original_url": metadata["url"], "rendition": rendition,
        }
        arm = {"status": "ok", "path": row["path"], "sha256": sha,
               "bytes": Path(row["path"]).stat().st_size,
               "width": row["width"], "height": row["height"], "mime": row["mime"],
               "variant": rendition, "elapsed_seconds": time.monotonic() - started,
               "events": [], "acquisition": "existing_read_only", "network_bytes": 0}
        record = {"index": index, **row, "candidate": candidate, "status": "selected",
                  "arms": {"original-1.0": arm}}
        if sha in cache:
            previous = copy.deepcopy(cache[sha])
            previous_arm = previous["arms"]["thumbnail-1.0"]
            relative = Path(previous_arm["path"]).name
            preserved = root.parent / "previous14" / relative
            assert preserved.is_file()
            record["cached_thumbnail"] = {
                **previous_arm, "path": str(preserved), "events": [], "elapsed_seconds": 0.0,
                "acquisition": "preserved_previous14", "network_bytes": 0,
            }
            record["cached_comparison"] = previous["comparison"]
            record["cached_revision"] = previous["candidate"]["rendition"]["revision"]
        manifest.append(record)
    inputs = {}
    for path in (snapshot / "assets.parquet", raw_manifest):
        with path.open("rb") as stream:
            inputs[str(path)] = hashlib.file_digest(stream, "sha256").hexdigest()
    save(root / "selection.json", {
        "rule": "権利適格CommonsをSHA単位でasset UUID最小代表。各domain50・各向き25を目標とし、"
                "不足する向きは残り候補を同じ固定順位で補充。"
                "各domainに幅1280以下1件を含め、他は幅1280超。"
                "SHA256(issue90-existing-v1:受信SHA256)順。pHashで統合しない。",
        "snapshot": str(snapshot), "input_hashes": inputs, "pool_sha_count": len(pool),
        "pool_excluded": excluded,
        "counts": dict(Counter(row["domain"] + ":" + row["orientation"] for row in manifest)),
        "small": sum(row["width"] <= 1280 for row in manifest), "records": manifest,
    })
    save(root / "manifest.json", manifest)
    save(root / "budget.json", {
        "created_at": datetime.now(UTC).isoformat(), "limits": {
            "api": 10, "original": 0, "thumbnail": 100,
        }, "used": {"api": 0, "original": 0, "thumbnail": 0},
        "original_source": "収集済み原本の読み取りのみ。本番DB接続なし。",
        "api_batch_max": 50, "thumbnail_width": 1280,
    })
    print("選定", len(manifest), "SHA pool", len(pool), "小原本", 2,
          "既存比較の候補", sum("cached_thumbnail" in row for row in manifest))


def fetch(root, policy_path):
    budget = json.loads((root / "budget.json").read_text())
    rows = json.loads((root / "manifest.json").read_text())
    adapter = CommonsAdapter(load_policy(policy_path, "wikimedia_commons"))
    events = []

    def observe(event, value=1):
        if event in {"api_request", "request"}:
            key = "api" if event == "api_request" else "thumbnail"
            if budget["used"][key] >= budget["limits"][key]:
                raise MeasurementLimit(key)
            budget["used"][key] += 1
            save(root / "budget.json", budget)
        events.append({"event": event, "value": value})

    adapter.observer = observe
    for offset in (0, 50):
        metadata_path = root / f"imageinfo-{offset}.json"
        if metadata_path.exists():
            response = json.loads(metadata_path.read_text())
        else:
            parameters = {
                "action": "query", "format": "json", "formatversion": 2, "maxlag": 5,
                "prop": "imageinfo", "iiprop": "url|size|mime|thumbmime|timestamp|sha1",
                "iiurlwidth": 1280,
                "titles": "|".join(row["candidate"]["title"] for row in rows[offset:offset + 50]),
            }
            response = adapter._get(ENDPOINT + "?" + urlencode(parameters))
            save(metadata_path, response)
        pages = {page["title"].replace("_", " "): page
                 for page in response.get("query", {}).get("pages", [])}
        for row in rows[offset:offset + 50]:
            if "thumbnail-1.0" in row["arms"]:
                continue
            page = pages.get(row["candidate"]["title"].replace("_", " "), {})
            infos = page.get("imageinfo", [])
            if not infos:
                row["status"] = "imageinfo_missing"
                continue
            info = infos[0]
            if info.get("sha1") != row["arms"]["original-1.0"]["variant"]["original"]["sha1"]:
                row["status"] = "original_revision_changed"
                continue
            rendition = row["candidate"]["rendition"]
            rendition.update(native_id=str(page["pageid"]), revision=info.get("timestamp"))
            row["arms"]["original-1.0"]["variant"] = copy.deepcopy(rendition)
            row["imageinfo"] = info
            if row["width"] <= 1280:
                row["status"] = "thumbnail_not_smaller"
                continue
            if not all(info.get(key) for key in (
                "thumburl", "thumbwidth", "thumbheight", "thumbmime",
            )):
                row["status"] = "thumbnail_missing"
                continue
            if "cached_thumbnail" in row:
                cached = row["cached_thumbnail"]
                if (cached["width"], cached["height"], cached["mime"]) == (
                    info["thumbwidth"], info["thumbheight"], info["thumbmime"],
                ):
                    with Path(cached["path"]).open("rb") as stream:
                        assert hashlib.file_digest(stream, "sha256").hexdigest() == cached["sha256"]
                    row["arms"]["thumbnail-1.0"] = cached
                    row["comparison"] = row["cached_comparison"]
                    row["status"] = "acquired"
                else:
                    row["status"] = "cached_variant_mismatch"
    save(root / "manifest.json", rows)
    adapter.finish()
    for row in rows:
        if row["status"] != "selected":
            continue
        target = root / f"{row['index']:03d}-thumbnail.image"
        if target.exists():
            raise FileExistsError(target)
        info = row["imageinfo"]
        rendition = copy.deepcopy(row["candidate"]["rendition"])
        rendition.update(variant="thumbnail", requested_width=1280, width=info["thumbwidth"],
                         height=info["thumbheight"], mime=info["thumbmime"])
        arm = {"path": str(target), "variant": rendition, "acquisition": "new_thumbnail"}
        events.clear()
        started = time.monotonic()
        try:
            adapter._get(info["thumburl"], target=target)
            adapter.finish()
            with target.open("rb") as stream:
                arm["sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
            with Image.open(target) as image:
                arm.update(width=image.width, height=image.height, mime=Image.MIME[image.format])
            arm.update(status="ok", bytes=target.stat().st_size)
            row["status"] = "acquired"
        except Exception as error:
            arm.update(status="failed", error=type(error).__name__, message=str(error))
            row["status"] = "acquisition_failed"
        arm.update(elapsed_seconds=time.monotonic() - started, events=list(events))
        row["arms"]["thumbnail-1.0"] = arm
        save(root / "manifest.json", rows)
    adapter.finish()
    print("通信枠", budget["used"], "成否", dict(Counter(row["status"] for row in rows)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--raw-manifest", type=Path)
    parser.add_argument("--policy", type=Path, default=Path("configs/source_policy.yaml"))
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    args.root.mkdir(exist_ok=True)
    if args.snapshot:
        freeze(args.root, args.snapshot, args.raw_manifest)
    if args.fetch:
        fetch(args.root, args.policy)


if __name__ == "__main__":
    main()
