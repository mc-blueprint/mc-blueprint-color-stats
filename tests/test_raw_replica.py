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


def test_publish_verified_batch(tmp_path):
    source = tmp_path / "staging"
    name = staging(source)
    target = tmp_path / "cache" / "batch"
    replica.publish(source, target)
    assert not source.exists()
    assert (target / name).read_bytes() == b"raw"


def test_corruption_does_not_publish(tmp_path):
    source = tmp_path / "staging"
    staging(source, expected="0" * 64)
    target = tmp_path / "cache" / "batch"
    with pytest.raises(ValueError, match="SHA-256"):
        replica.publish(source, target)
    assert source.is_dir()
    assert not target.exists()


def test_existing_batch_is_not_replaced(tmp_path):
    source = tmp_path / "staging"
    staging(source)
    target = tmp_path / "existing"
    target.mkdir()
    (target / "keep").write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        replica.publish(source, target)
    assert (target / "keep").read_bytes() == b"keep"


def test_source_monitor_blocks_staging(tmp_path, monkeypatch):
    monkeypatch.setattr(replica.socket, "gethostname", lambda: "ubuntu-1")
    monkeypatch.setattr(replica, "storage_available", lambda stage: False)
    target = tmp_path / "staging"
    with pytest.raises(RuntimeError, match="保留"):
        replica.stage(target, [])
    assert not target.exists()
