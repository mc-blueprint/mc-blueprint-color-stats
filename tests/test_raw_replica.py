"""原本複製の公開境界と内容検証。"""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "raw_replica", Path(__file__).resolve().parents[1] / "ops/deploy/raw-replica.py"
)
replica = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replica)


def staging(root, data=b"raw", expected=None):
    root.mkdir()
    sha256 = hashlib.sha256(data).hexdigest()
    name = sha256 + ".jpg"
    (root / name).write_bytes(data)
    (root / "manifest.json").write_text(json.dumps({"files": [{
        "name": name, "sha256": expected or sha256, "bytes": len(data),
    }]}))
    return name


@pytest.fixture
def config(tmp_path):
    (tmp_path / "staging").mkdir()
    (tmp_path / "batches").mkdir()
    return {"root": str(tmp_path), "max_bytes": 150_000_000_000}


def test_publish_verified_batch(tmp_path, config):
    source = tmp_path / "staging" / "batch"
    name = staging(source)
    target = tmp_path / "batches" / "batch"
    replica.publish(source, target, config)
    assert not source.exists()
    assert (target / name).read_bytes() == b"raw"


def test_corruption_does_not_publish(tmp_path, config):
    source = tmp_path / "staging" / "batch"
    staging(source, expected="0" * 64)
    target = tmp_path / "batches" / "batch"
    with pytest.raises(ValueError, match="SHA-256"):
        replica.publish(source, target, config)
    assert source.is_dir()
    assert not target.exists()


def test_existing_batch_is_not_replaced(tmp_path, config):
    source = tmp_path / "staging" / "batch"
    staging(source)
    target = tmp_path / "batches" / "existing"
    target.mkdir()
    (target / "keep").write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        replica.publish(source, target, config)
    assert (target / "keep").read_bytes() == b"keep"


def test_source_monitor_blocks_staging(tmp_path, monkeypatch):
    from colorstats.queue import storage

    monkeypatch.setattr(replica.socket, "gethostname", lambda: "ubuntu-1")
    monkeypatch.setattr(storage, "storage_available", lambda stage: False)
    target = tmp_path / "staging"
    with pytest.raises(RuntimeError, match="保留"):
        replica.stage(target, [], {"files": []})
    assert not target.exists()


def test_capacity_counts_staging_and_published(tmp_path, config):
    source = tmp_path / "staging" / "batch"
    staging(source)
    (tmp_path / "batches" / "other").write_bytes(b"existing")
    config["max_bytes"] = replica.usage(tmp_path) - 1
    with pytest.raises(ValueError, match="容量上限"):
        replica.publish(source, tmp_path / "batches" / "batch", config)
    assert source.exists()
    config["max_bytes"] += 1
    replica.publish(source, tmp_path / "batches" / "batch", config)


@pytest.mark.parametrize(
    "condition", ["success", "running", "missing", "empty", "reference", "sha"]
)
def test_prune_requires_all_success_and_no_references(tmp_path, config, condition):
    target = tmp_path / "batches" / "batch"
    staging(target)
    completion = {
        "batch": "batch", "manifest_sha256": replica.digest(target / "manifest.json"),
        "expected_gpu_jobs": ["segment-1", "other-2"],
        "gpu_jobs": [{"job_id": name, "status": "succeeded"}
                     for name in ("segment-1", "other-2")], "references": [],
    }
    if condition == "running":
        completion["gpu_jobs"][0]["status"] = "running"
    elif condition == "missing":
        completion["gpu_jobs"].pop()
    elif condition == "empty":
        completion["expected_gpu_jobs"] = []
        completion["gpu_jobs"] = []
    elif condition == "reference":
        completion["references"] = ["reader"]
    elif condition == "sha":
        completion["manifest_sha256"] = "0" * 64
    if condition == "success":
        replica.prune(target, completion, config)
        assert not target.exists()
    else:
        with pytest.raises(ValueError, match="保持"):
            replica.prune(target, completion, config)
        assert target.exists()


def test_prune_rejects_outside(tmp_path, config):
    outside = tmp_path / "outside"
    staging(outside)
    with pytest.raises(ValueError, match="batches直下"):
        replica.prune(outside, {}, config)


def test_cache_lock_prevents_overlapping_operations(tmp_path, config):
    source = tmp_path / "staging" / "batch"
    staging(source)
    with replica.cache_lock(tmp_path), pytest.raises(FileExistsError):
        replica.publish(source, tmp_path / "batches" / "batch", config)
    assert source.exists()


def test_capacity_admission_includes_transfer(tmp_path, config, capsys):
    (tmp_path / "partial").write_bytes(b"abc")
    config["max_bytes"] = 10
    replica.capacity(config, 7)
    assert json.loads(capsys.readouterr().out)["cache_bytes"] == 3
    with pytest.raises(ValueError, match="転送を保留"):
        replica.capacity(config, 8)


@pytest.mark.parametrize("mismatch", [False, True])
def test_stage_records_verified_origin(tmp_path, monkeypatch, mismatch):
    from colorstats.queue import storage

    monkeypatch.setattr(replica.socket, "gethostname", lambda: "ubuntu-1")
    monkeypatch.setattr(storage, "storage_available", lambda stage: True)
    raw = tmp_path / "raw"
    raw.mkdir()
    sha256 = hashlib.sha256(b"original").hexdigest()
    source = raw / (sha256 + ".jpg")
    source.write_bytes(b"original")
    monkeypatch.setattr(replica, "RAW_ROOTS", (raw,))
    origin = {"source": str(source), "sha256": "0" * 64 if mismatch else sha256,
              "asset_id": "asset", "source_run_id": "collect-run", "source_stage": "collect",
              "input_run_id": None, "license_class": "open"}
    target = tmp_path / "transfer"
    if mismatch:
        with pytest.raises(ValueError, match="由来記録"):
            replica.stage(target, [source], {"files": [origin]})
        assert not (target / "manifest.json").exists()
    else:
        replica.stage(target, [source], {"files": [origin]})
        manifest = json.loads((target / "manifest.json").read_text())
        assert manifest["files"][0]["origins"] == [origin]
