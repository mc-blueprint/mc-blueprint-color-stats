"""GPU計測の公開集計とprivate記録を分離し、画像別の再混入を防ぐ。"""

import hashlib
import json
from pathlib import Path

import pytest
from bench.issue130.gpu import save_summary


def test_gpu_writer_keeps_records_private_and_hashes_actual_bytes(tmp_path):
    records = [{"seconds": 1.5, "runtime": {
        "peak_allocated_bytes": 4, "oneformer_peak_allocated_bytes": 6,
        "peak_reserved_bytes": 8, "oneformer_peak_reserved_bytes": 7},
        "variants": {"baseline": {"pixels": 100, "candidate_count": 2}}},
        {"seconds": 2.5, "runtime": {
            "peak_allocated_bytes": 5, "oneformer_peak_allocated_bytes": 3,
            "peak_reserved_bytes": 9, "oneformer_peak_reserved_bytes": 4},
         "variants": {"baseline": {"pixels": 200, "candidate_count": 3}}}]
    save_summary(tmp_path, records, {"gpu": "fixture", "quality_eligible": False})
    private = tmp_path / "records.json"
    assert json.loads(private.read_text("utf-8")) == records
    summary = json.loads((tmp_path / "summary.json").read_text("utf-8"))
    assert "records" not in summary and "variants" not in summary
    assert summary["images"] == 2 and summary["seconds"] == 4
    assert summary["peak_allocated_bytes"] == 6 and summary["peak_reserved_bytes"] == 9
    assert summary["records_sha256"] == hashlib.sha256(private.read_bytes()).hexdigest()
    assert summary["records_hash_format"] == "sha256-raw-private"
    with pytest.raises(FileExistsError):
        save_summary(tmp_path, records, {})


def test_fixed_gpu_publications_contain_no_image_records():
    root = Path(__file__).resolve().parents[1] / "bench/issue130"
    for host in ("ubuntu1", "ubuntu2"):
        summary = json.loads((root / f"gpu-{host}.json").read_text("utf-8"))
        assert "records" not in summary
        assert summary["images"] == 3
        assert summary["seconds"] > 0
        assert summary["peak_reserved_bytes"] >= summary["peak_allocated_bytes"] > 0
        assert summary["records_hash_format"] == "sha256-raw-private"
        assert len(bytes.fromhex(summary["records_sha256"])) == 32
