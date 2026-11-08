"""Git保存内容と改行の異なる作業コピーで品質証跡が照合できることを検証する。"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from bench.issue81.evaluate import text_digest
from bench.issue121.decision import main

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "bench/issue121"


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_decision_evidence_matches_git_blob(tmp_path, monkeypatch, newline):
    source = BENCH / "legacy-definition.json"
    content = source.read_bytes().replace(b"\r\n", b"\n")
    legacy = tmp_path / source.name
    legacy.write_bytes(content)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "core.autocrlf=false",
                    "add", legacy.name], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=証跡テスト",
                    "-c", "user.email=evidence@example.invalid", "-c", "commit.gpgsign=false",
                    "commit", "-qm", "test: LFの根拠を固定する"], check=True)
    blob = subprocess.check_output(["git", "-C", str(tmp_path), "show",
                                    f"HEAD:{legacy.name}"])
    assert blob == content
    legacy.write_bytes(content.replace(b"\n", newline))
    output = tmp_path / "decision.json"
    argv = ["decision", "--legacy", str(legacy), "--output", str(output)]
    for flag, name in (("paired", "paired-summary"), ("ade", "ade-summary"),
                       ("owned", "owned-proof"), ("class-info", "class-info-provenance"),
                       ("human", "human-summary"), ("aerial", "aerial-summary"),
                       ("gpu", "gpu-ubuntu1"), ("gpu", "gpu-ubuntu2")):
        argv += [f"--{flag}", str(BENCH / f"{name}.json")]
    monkeypatch.setattr(sys, "argv", argv)
    main()
    decision = json.loads(output.read_text(encoding="utf-8"))
    assert decision["evidence_hash_format"] == "sha256-lf-normalized"
    assert decision["evidence"][str(legacy)] == hashlib.sha256(blob).hexdigest()
    assert all(value == text_digest(Path(path)) for path, value in decision["evidence"].items())


def test_fixed_decision_and_handoff_evidence():
    decision = json.loads((BENCH / "decision.json").read_text(encoding="utf-8"))
    assert decision["evidence_hash_format"] == "sha256-lf-normalized"
    for path, expected in decision["evidence"].items():
        assert text_digest(ROOT / path) == expected, path
    for name in ("handoff.json", "handoff-verification.json"):
        handoff = json.loads((BENCH / name).read_text(encoding="utf-8"))
        assert handoff["decision_hash_format"] == "sha256-lf-normalized"
        assert handoff["decision_sha256"] == text_digest(BENCH / "decision.json")


def test_public_gpu_summaries_contain_only_aggregates():
    for host in ("ubuntu1", "ubuntu2"):
        summary = json.loads((BENCH / f"gpu-{host}.json").read_text(encoding="utf-8"))
        assert "records" not in summary
        assert summary["images"] == 3
        assert summary["total_seconds"] > 0
        assert summary["peak_reserved_bytes"] >= summary["peak_allocated_bytes"] > 0
        assert summary["records_hash_format"] == "sha256-raw-private"
        assert len(bytes.fromhex(summary["records_sha256"])) == 32
