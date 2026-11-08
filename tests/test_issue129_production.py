import hashlib
import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from bench.issue129 import production


def test_投入中の停止では新規API処理を開始せず再開は同じjobを使う(tmp_path, monkeypatch):
    root = tmp_path
    review = root / "review-freeze.json"
    review.write_text("{}")
    identifier, job_id = str(uuid.uuid4()), uuid.uuid4()
    identity = production.gate.identity(b"")
    plan = {"identity": identity, "review_sha256": hashlib.sha256(review.read_bytes()).hexdigest(),
            "review_ids": [identifier], "jobs": {}, "holds": {}, "code_version": "fixture",
            "inputs": {identifier: {"identity": identity, "source_sha256": "a" * 64}}}
    production.save(root / "plan.json", plan)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(root))
    monkeypatch.setenv("COLORSTATS_IMAGE_GATE_CONCURRENCY", "4")
    monkeypatch.setattr(production.signal, "signal", lambda *args: None)
    session = MagicMock()
    session.__enter__.return_value.get.return_value.payload = {
        "identity": identity, "source_sha256": "a" * 64,
    }
    monkeypatch.setattr(production, "Session", lambda engine: session)
    state = {"jobs": {}, "parent_nusd": 0, "v2_nusd": 0,
             "cap_nusd": 50 * production.NUSD, "stopped": False}
    monkeypatch.setattr(production, "state", lambda *args: state.copy())
    submitted, enqueued = [], []

    def enqueue(*args, **kwargs):
        enqueued.append(identifier)
        (root / "smoke.stop").touch()
        state["jobs"] = {"pending": 1}
        return job_id

    monkeypatch.setattr(production.gate, "enqueue", enqueue)
    claims = [SimpleNamespace(id=job_id)]

    def claim(*args, **kwargs):
        assert not (root / "smoke.stop").exists()
        return claims.pop() if claims else None

    queue = SimpleNamespace(claim=claim)
    monkeypatch.setattr(production, "Queue", lambda *args: queue)

    def process(claim):
        submitted.append(claim.id)
        state["jobs"] = {"succeeded": 1}

    monkeypatch.setattr(production, "Worker", lambda *args, **kwargs: SimpleNamespace(
        queue=queue, _run_claim=process, _stop_prepare=lambda: None))
    production.run(None, root, "smoke")
    assert enqueued == [identifier] and submitted == []
    assert json.loads((root / "smoke-end.json").read_text())["reason"] == "stop_requested"
    (root / "smoke.stop").rename(root / "smoke.stopped-before-resume")
    production.run(None, root, "smoke")
    assert enqueued == [identifier] and submitted == [job_id]
    assert json.loads((root / "smoke-end.json").read_text())["reason"] == "all_terminal"


def test_再開時のrunningはリース失効後に再取得して完了する(tmp_path, monkeypatch):
    review = tmp_path / "review-freeze.json"
    review.write_text("{}")
    identifier, job_id = str(uuid.uuid4()), uuid.uuid4()
    production.save(tmp_path / "plan.json", {
        "identity": production.gate.identity(b""),
        "review_sha256": hashlib.sha256(review.read_bytes()).hexdigest(),
        "review_ids": [identifier], "jobs": {identifier: str(job_id)}, "holds": {},
    })
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("COLORSTATS_IMAGE_GATE_CONCURRENCY", "4")
    monkeypatch.setattr(production.signal, "signal", lambda *args: None)
    state = {"jobs": {"running": 1}, "parent_nusd": 0, "v2_nusd": 0,
             "cap_nusd": 50 * production.NUSD, "stopped": False}
    monkeypatch.setattr(production, "state", lambda *args: state.copy())
    elapsed, submitted = [], []
    claimed = False

    def claim(*args, **kwargs):
        nonlocal claimed
        assert kwargs["job_ids"] == [job_id]
        if len(elapsed) < 2 or claimed:
            return None
        claimed = True
        return SimpleNamespace(id=job_id)

    def sleep(seconds):
        assert state["jobs"] == {"running": 1} and not submitted
        assert len(elapsed) < 2
        elapsed.append(seconds)

    def process(claim):
        assert len(elapsed) == 2
        submitted.append(claim.id)
        state["jobs"] = {"succeeded": 1}

    queue = SimpleNamespace(claim=claim)
    monkeypatch.setattr(production.time, "sleep", sleep)
    monkeypatch.setattr(production, "Queue", lambda *args: queue)
    monkeypatch.setattr(production, "Worker", lambda *args, **kwargs: SimpleNamespace(
        queue=queue, _run_claim=process, _stop_prepare=lambda: None))
    production.run(None, tmp_path, "smoke")
    assert elapsed == [1, 1] and submitted == [job_id]
    result = json.loads((tmp_path / "smoke-end.json").read_text())
    assert result["reason"] == "all_terminal" and result["jobs"] == {"succeeded": 1}
