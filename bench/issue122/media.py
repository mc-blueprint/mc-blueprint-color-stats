"""既存媒体から#122専用コピーを作り、一時unit用の読取り専用参照を固定する。"""

import argparse
import importlib.util
import os
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from uuid import UUID, uuid4

from bench.issue122.production import CODE, ROOT, database, read, save
from sqlalchemy import select
from sqlalchemy.orm import Session

from colorstats import retention
from colorstats.analyze.segment import _hash
from colorstats.queue import Queue
from colorstats.schema.models import Asset, Job, ProcessingRun

MEDIA = ROOT / "media-r3"
MIRROR = MEDIA / "root"


def stage_raw(replica, sources, provenance):
    """既存stageで別試行先を完成させ、未完成の旧stageを保全して確定先へ移す。"""
    staging = MEDIA / "raw"
    if not (staging / "manifest.json").exists():
        attempt = MEDIA / ("raw-attempt-" + uuid4().hex)
        replica.stage(attempt, sorted(sources), {"files": provenance})
        if staging.exists():
            staging.rename(MEDIA / ("raw-incomplete-" + uuid4().hex))
        attempt.rename(staging)
    return staging


def copy_verified(source, target, sha256):
    """一時ファイルをSHA照合後に公開する。既存確定先の不一致は置換せず停止する。"""
    if _hash(source) != sha256:
        raise ValueError("prepの専用コピーが不一致です")
    if target.exists():
        if _hash(target) != sha256:
            raise ValueError("prepの専用コピーが不一致です")
        return
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix="." + target.name + ".",
                                     suffix=".partial", delete=False) as stream:
        temporary = Path(stream.name)
    shutil.copyfile(source, temporary)
    if _hash(source) != sha256 or _hash(temporary) != sha256:
        raise ValueError("prepの専用コピーが不一致です")
    temporary.chmod(0o600)
    temporary.replace(target)


def raw(db):
    """既存raw-replicaの媒体監視・由来照合付きstageを使う。原本は変更しない。"""
    module_spec = importlib.util.spec_from_file_location(
        "raw_replica", CODE / "ops/deploy/raw-replica.py")
    replica = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(replica)
    rows = [row for row in read(ROOT / "plan.json")["rows"] if row["status"] == "ready"]
    provenance, sources = [], set()
    with Session(db) as session:
        collected = session.execute(select(ProcessingRun.id, ProcessingRun.output_paths)
                                    .join(Job, Job.run_id == ProcessingRun.id)
                                    .where(Job.stage == "collect", Job.status == "succeeded"))
        by_path = {path: run_id for run_id, paths in collected for path in paths.values()}
        for row in rows:
            asset = session.get(Asset, UUID(row["asset_id"]))
            retention.assert_usable(session, asset.id, images=True)
            run_id = by_path.get(asset.storage_path)
            if run_id is None:
                raise ValueError("原画像の成功collectがありません")
            source = Path(asset.storage_path).resolve(strict=True)
            if str(source) != asset.storage_path or asset.sha256 != row["sha256"]:
                raise ValueError("原画像とcollect由来が一致しません")
            sources.add(source)
            provenance.append({"asset_id": str(asset.id), "source_run_id": str(run_id),
                               "source_stage": "collect", "input_run_id": None,
                               "sha256": asset.sha256, "source": str(source),
                               "license_class": asset.license_class})
    MEDIA.mkdir(mode=0o700, parents=True, exist_ok=True)
    save(MEDIA / "raw-provenance.json", {"files": provenance})
    staging = stage_raw(replica, sources, provenance)
    manifest = read(staging / "manifest.json")
    queue = Queue(db, timeout=60)
    for record in manifest["files"]:
        source = Path(record["source"])
        target = MIRROR / source.relative_to("/")
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not target.exists():
            os.link(staging / record["name"], target)
        if _hash(target) != record["sha256"]:
            raise ValueError("原画像の専用コピーが不一致です")
        with queue._transaction() as session:
            retention.lock(session)
            for origin in record["origins"]:
                for path in (target, staging / record["name"]):
                    retention.register_file(session, UUID(origin["asset_id"]), "ubuntu-2",
                                            path, "replica")
    save(MEDIA / "raw-complete.json", {"files": len(manifest["files"]),
                                       "manifest_sha256": _hash(staging / "manifest.json")})
    print("raw_replica_complete files=" + str(len(manifest["files"])), flush=True)


def prep(db):
    """旧prepのbyte列と元パスを専用コピーへ保ち、元runを更新しない。"""
    rows = [row for row in read(ROOT / "plan.json")["rows"] if row["status"] == "ready"]
    records = []
    roots = set()
    queue = Queue(db, timeout=60)
    for row in rows:
        source = Path(row["input_path"])
        if not source.is_relative_to("/mnt/data/derived"):
            raise ValueError("想定外のprep媒体です")
        target = MIRROR / source.relative_to("/")
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        copy_verified(source, target, row["input_sha256"])
        roots.add(str(Path(*source.parts[:5])))
        records.append({"asset_id": row["asset_id"], "source": str(source),
                        "copy": str(target), "sha256": row["input_sha256"]})
        with queue._transaction() as session:
            retention.lock(session)
            retention.register_file(session, UUID(row["asset_id"]), "ubuntu-2", target, "replica")
    save(MEDIA / "prep-complete.json", {"records": records, "bind_roots": sorted(roots)})
    print("prep_replica_complete assets=" + str(len(records)), flush=True)


def check(db):
    raw_manifest = read(MEDIA / "raw/manifest.json")
    prepared = read(MEDIA / "prep-complete.json")
    raw_by_source = {row["source"]: row for row in raw_manifest["files"]}
    counts = Counter()
    with Session(db) as session:
        for row in prepared["records"]:
            asset = session.get(Asset, UUID(row["asset_id"]))
            retention.assert_usable(session, asset.id, images=True)
            original = raw_by_source[asset.storage_path]
            assert original["sha256"] == asset.sha256
            assert _hash(MIRROR / Path(asset.storage_path).relative_to("/")) == asset.sha256
            assert _hash(row["copy"]) == row["sha256"]
            counts["assets"] += 1
    save(MEDIA / "verified.json", {"counts": counts,
                                    "raw_manifest_sha256": _hash(MEDIA / "raw/manifest.json"),
                                    "prep_manifest_sha256": _hash(MEDIA / "prep-complete.json"),
                                    "bind_roots": ["/srv/colorstats", *prepared["bind_roots"]]})
    print("all_media_verified assets=" + str(counts["assets"]), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("raw", "prep", "check"))
    args = parser.parse_args()
    os.umask(0o077)
    db = database()
    try:
        {"raw": raw, "prep": prep, "check": check}[args.action](db)
    finally:
        db.dispose()


if __name__ == "__main__":
    main()
