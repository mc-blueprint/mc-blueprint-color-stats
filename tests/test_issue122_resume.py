"""固定一覧の差替えと、未完成artifact・コピーの再試行を検証する。"""

import hashlib
import importlib.util
import json
from contextlib import nullcontext
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("pwd")

from bench.issue122 import media, statistics


def test_changed_review_freeze_stops_selection(tmp_path, monkeypatch):
    review = tmp_path / "review-freeze.json"
    frozen = b'{"records":[{"asset_id":"held"}]}'
    review.write_bytes(frozen)
    monkeypatch.setattr(statistics, "GATE", tmp_path)
    monkeypatch.setattr(statistics, "ROOT", tmp_path)
    monkeypatch.setattr(statistics, "OLD", tmp_path)
    monkeypatch.setattr(statistics, "REVIEW_SHA256", hashlib.sha256(frozen).hexdigest(),
                        raising=False)
    monkeypatch.setattr(statistics, "Session", lambda db: nullcontext(None))
    (tmp_path / "plan.json").write_text('{"rows":[]}')
    for host in ("ubuntu1", "ubuntu2"):
        (tmp_path / host).mkdir()
        (tmp_path / host / "records.json").write_text('{}')
    (tmp_path / "selection.json").write_text('{"assets":[],"taxonomy_version":"test"}')
    statistics.selection(None)
    review.write_text('{"records":[]}')
    with pytest.raises(ValueError, match="人確認.*SHA"):
        statistics.selection(None)


def test_incomplete_snapshot_is_preserved_and_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(statistics, "OUTPUT", tmp_path)
    selected = {"assets": []}
    attempts = []

    def execute(db, selection, output, **kwargs):
        output.mkdir(exist_ok=False)
        attempts.append(output)
        if len(attempts) == 1:
            (output / "partial").write_bytes(b"keep")
            raise OSError("中断")
        manifest = {"snapshot_id": "complete", "selection_hash": statistics.digest(selection)}
        (output / "manifest.json").write_text(json.dumps(manifest))
        return manifest

    monkeypatch.setattr(statistics, "execute", execute)
    monkeypatch.setattr(statistics, "verify", lambda path, expected: None)
    with pytest.raises(OSError, match="中断"):
        statistics.ensure_snapshot(None, selected, {})
    path, manifest = statistics.ensure_snapshot(None, selected, {})
    assert path == tmp_path / "snapshot"
    assert manifest["snapshot_id"] == "complete" and (path / "manifest.json").exists()
    assert attempts[0] != attempts[1]
    assert [p.read_bytes() for p in tmp_path.glob("snapshot-incomplete-*/partial")] == [b"keep"]
    assert statistics.ensure_snapshot(None, selected, {}) == (path, manifest)
    assert len(attempts) == 2


def test_completed_snapshot_accepts_same_selection_in_different_order(tmp_path, monkeypatch):
    monkeypatch.setattr(statistics, "OUTPUT", tmp_path)
    monkeypatch.setattr(statistics, "verify", lambda path, expected: None)
    selected = {"assets": [{"asset_id": "b"}, {"asset_id": "a"}],
                "subject_attribute_run_ids": ["b", "a"]}
    normalized = {"assets": [{"asset_id": "a"}, {"asset_id": "b"}],
                  "subject_attribute_run_ids": ["a", "b"]}
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    manifest = {"snapshot_id": "complete", "selection_hash": statistics.digest(normalized)}
    (snapshot / "manifest.json").write_text(json.dumps(manifest))
    assert statistics.ensure_snapshot(None, selected, {}) == (snapshot, manifest)
    assert selected["assets"][0]["asset_id"] == "b"
    assert selected["subject_attribute_run_ids"] == ["b", "a"]


@pytest.mark.parametrize("failure", ["interrupted", "corrupt"])
def test_prep_copy_is_published_only_after_verification(tmp_path, monkeypatch, failure):
    source, target = tmp_path / "source", tmp_path / "copy"
    source.write_bytes(b"complete")
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    copyfile = media.shutil.copyfile
    partials = []

    def broken_copy(src, dst):
        Path(dst).write_bytes(b"partial")
        partials.append(Path(dst))
        if failure == "interrupted":
            raise OSError("中断")

    monkeypatch.setattr(media.shutil, "copyfile", broken_copy)
    with pytest.raises((OSError, ValueError)):
        media.copy_verified(source, target, expected)
    assert not target.exists()
    assert partials[0].read_bytes() == b"partial"
    monkeypatch.setattr(media.shutil, "copyfile", copyfile)
    media.copy_verified(source, target, expected)
    assert target.read_bytes() == b"complete"
    assert partials[0].read_bytes() == b"partial"


def test_raw_stage_retries_without_discarding_incomplete_outputs(tmp_path, monkeypatch):
    from colorstats.queue import storage

    spec = importlib.util.spec_from_file_location(
        "raw_replica_resume", Path(__file__).resolve().parents[1] / "ops/deploy/raw-replica.py")
    replica = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replica)
    monkeypatch.setattr(replica.socket, "gethostname", lambda: "ubuntu-1")
    monkeypatch.setattr(storage, "storage_available", lambda stage: True)
    source_root = tmp_path / "source"
    source_root.mkdir()
    sha256 = hashlib.sha256(b"raw").hexdigest()
    source = source_root / (sha256 + ".jpg")
    source.write_bytes(b"raw")
    monkeypatch.setattr(replica, "RAW_ROOTS", (source_root,))
    monkeypatch.setattr(media, "MEDIA", tmp_path / "media")
    media.MEDIA.mkdir()
    (media.MEDIA / "raw").mkdir()
    (media.MEDIA / "raw/partial").write_bytes(b"keep")
    provenance = [{"asset_id": str(uuid4()), "source_run_id": str(uuid4()),
                   "source": str(source), "source_stage": "collect", "input_run_id": None,
                   "sha256": sha256}]
    copyfile = replica.shutil.copyfile
    interrupted = []

    def broken_copy(src, dst):
        Path(dst).write_bytes(b"partial")
        interrupted.append(Path(dst))
        raise OSError("中断")

    monkeypatch.setattr(replica.shutil, "copyfile", broken_copy)
    with pytest.raises(OSError, match="中断"):
        media.stage_raw(replica, {source}, provenance)
    monkeypatch.setattr(replica.shutil, "copyfile", copyfile)
    result = media.stage_raw(replica, {source}, provenance)
    assert result == media.MEDIA / "raw"
    manifest = json.loads((result / "manifest.json").read_text())
    assert manifest["files"][0]["sha256"] == sha256
    assert (result / source.name).read_bytes() == b"raw"
    assert interrupted[0].read_bytes() == b"partial"
    assert [p.read_bytes() for p in media.MEDIA.glob("raw-incomplete-*/partial")] == [b"keep"]
