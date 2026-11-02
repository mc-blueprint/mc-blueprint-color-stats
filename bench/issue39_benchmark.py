"""Issue #39: ubuntu-1 CPUでprep/colorのプロセス方式を比較する。"""

from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from colorstats.queue.core import Claim

ROOT = Path("/var/tmp/colorstats-bench39")
MODES = (("spawn1", 1), ("batch16", 16), ("batch64", 64), ("resident", 0))


def _rss_tree(pid: int) -> int:
    pending = [pid]
    seen = set()
    total = 0
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        try:
            status = Path(f"/proc/{current}/status").read_text()
            for line in status.splitlines():
                if line.startswith("VmRSS:"):
                    total += int(line.split()[1]) * 1024
                    break
            children = Path(f"/proc/{current}/task/{current}/children").read_text()
            pending.extend(int(child) for child in children.split())
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
    return total


class RssSampler:
    def __init__(self):
        self.peak = 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self):
        while not self.stop.is_set():
            self.peak = max(self.peak, _rss_tree(os.getpid()))
            self.stop.wait(0.02)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()
        self.peak = max(self.peak, _rss_tree(os.getpid()))


def _run(stage: str, claim: Claim):
    from importlib import import_module

    return import_module(f"colorstats.analyze.{stage}").prepare(claim)


def _child_one(stage, claim, connection):
    try:
        connection.send((True, _run(stage, claim)))
    except Exception as error:
        connection.send((False, f"{type(error).__name__}: {error}"))
    finally:
        connection.close()


def _child_batch(stage, claims, connection):
    prepared = []
    try:
        for index, claim in enumerate(claims):
            try:
                prepared.append(_run(stage, claim))
            except Exception as error:
                connection.send((False, index, f"{type(error).__name__}: {error}"))
                return
        connection.send((True, prepared))
    finally:
        connection.close()


def _child_resident(stage, connection):
    while True:
        claim = connection.recv()
        if claim is None:
            break
        try:
            connection.send((True, _run(stage, claim)))
        except Exception as error:
            connection.send((False, f"{type(error).__name__}: {error}"))
    connection.close()


def _claim(stage: str, asset_id: str, output: Path, *, bad_input=False) -> Claim:
    token = uuid4()
    if stage == "prep":
        payload = {
            "input_path": str(ROOT / "input" / asset_id) if not bad_input else "/dev/null",
            "derived_path": str(output),
            "license_class": "open",
            "taxonomy_version": "v1",
        }
    else:
        source = ROOT / "prep-reference.json"
        input_path = json.loads(source.read_text())[asset_id]
        payload = {
            "input_path": str(input_path) if not bad_input else "/dev/null",
            "output_path": str(output),
            "input_run_id": None,
            "license_class": "open",
            "taxonomy_version": "v1",
        }
    return Claim(
        id=uuid4(),
        token=token,
        stage=stage,
        asset_id=UUID(asset_id),
        config_hash="0" * 64,
        payload=payload,
        attempt=1,
        started_at=datetime.now(UTC),
    )


def _publish(claim: Claim, prepared) -> list[Path]:
    published = []
    for temporary, target in prepared.files:
        directory = target.parent / f".output-{claim.token}-{uuid4()}"
        directory.mkdir()
        path = directory / target.name
        temporary.replace(path)
        published.append(path)
    return published


def _run_spawn(context, stage, claim):
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_child_one, args=(stage, claim, sender))
    process.start()
    sender.close()
    try:
        success, result = receiver.recv()
        process.join()
        if not success:
            raise RuntimeError(result)
        return result
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
        process.join()
        process.close()


def _run_batch(context, stage, claims):
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_child_batch, args=(stage, claims, sender))
    process.start()
    sender.close()
    try:
        result = receiver.recv()
        process.join()
        return result
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
        process.join()
        process.close()


def _run_resident(context, stage, claims, publish=True):
    receiver, sender = context.Pipe(duplex=True)
    process = context.Process(target=_child_resident, args=(stage, sender))
    process.start()
    sender.close()
    published = []
    failures = 0
    try:
        for claim in claims:
            receiver.send(claim)
            success, result = receiver.recv()
            if success:
                if publish:
                    published.extend(_publish(claim, result))
            else:
                failures += 1
        return published, failures
    finally:
        receiver.send(None)
        process.join()
        receiver.close()
        process.close()


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_mode(stage: str, mode: str, batch_size: int, asset_ids: list[str]) -> dict:
    context = mp.get_context("spawn")
    output = ROOT / "results" / stage / mode
    if output.exists():
        raise FileExistsError(f"既存出力を再利用しません: {output}")
    output.mkdir(parents=True)
    claims = [
        _claim(stage, asset_id, output / f"{asset_id}.{'jpg' if stage == 'prep' else 'json'}")
        for asset_id in asset_ids
    ]
    published = []
    started = time.perf_counter()
    with RssSampler() as sampler:
        if mode == "spawn1":
            for claim in claims:
                published.extend(_publish(claim, _run_spawn(context, stage, claim)))
        elif mode.startswith("batch"):
            for start in range(0, len(claims), batch_size):
                batch = claims[start : start + batch_size]
                success, result = _run_batch(context, stage, batch)
                if not success:
                    raise RuntimeError(f"batch failed at {result}")
                for claim, prepared in zip(batch, result, strict=True):
                    published.extend(_publish(claim, prepared))
        else:
            published, failures = _run_resident(context, stage, claims)
            if failures:
                raise RuntimeError(f"resident failures: {failures}")
    elapsed = time.perf_counter() - started
    hashes = {path.name: _hash(path) for path in sorted(published)}
    output_bytes = sum(path.stat().st_size for path in published)
    return {
        "stage": stage,
        "mode": mode,
        "items": len(asset_ids),
        "elapsed_seconds": round(elapsed, 3),
        "items_per_second": round(len(asset_ids) / elapsed, 3),
        "max_rss_mib": round(sampler.peak / 1024**2, 2),
        "output_bytes": output_bytes,
        "bytes_per_item": round(output_bytes / len(asset_ids)),
        "files": len(published),
        "hashes": hashes,
    }


def _failure_probe(stage: str, asset_ids: list[str]) -> dict:
    context = mp.get_context("spawn")
    result = {}
    for mode, size in MODES:
        count = size or 16
        output = ROOT / "failure" / stage / mode
        output.mkdir(parents=True, exist_ok=True)
        claims = [
            _claim(stage, asset_id, output / f"{i}-{asset_id}.out")
            for i, asset_id in enumerate(asset_ids[:count])
        ]
        position = count // 2
        claims[position] = _claim(
            stage, asset_ids[position], output / "invalid.out", bad_input=True
        )
        if mode == "spawn1":
            try:
                _run_spawn(context, stage, claims[position])
            except RuntimeError:
                result[mode] = {"failed_asset": 1, "retry_scope": 1}
        elif mode.startswith("batch"):
            success, failed_index, _ = _run_batch(context, stage, claims)
            result[mode] = {
                "failed_asset": 1,
                "failed_index": failed_index,
                "computed_before_failure": failed_index,
                "committed_before_failure": 0 if not success else failed_index,
                "retry_scope": len(claims) if not success else 1,
            }
        else:
            published, failures = _run_resident(context, stage, [claims[position], claims[0]])
            result[mode] = {
                "failed_asset": failures,
                "process_reused_after_failure": len(published) == 1,
                "retry_scope": failures,
            }
    return result


def main():
    import sys

    stage = sys.argv[1]
    if stage not in ("prep", "color"):
        raise SystemExit("stage must be prep or color")
    manifest = [line.split("\t") for line in (ROOT / "manifest.tsv").read_text().splitlines()]
    asset_ids = [asset_id for asset_id, _ in manifest]
    if len(asset_ids) != 754 or len(set(asset_ids)) != 754:
        raise ValueError("manifestは重複のない754件である必要があります")
    modes = list(MODES if stage == "prep" else reversed(MODES))
    summaries = []
    for mode, size in modes:
        summary = _run_mode(stage, mode, size, asset_ids)
        summaries.append(summary)
        print(json.dumps({key: value for key, value in summary.items() if key != "hashes"}))
    baseline = summaries[0]["hashes"] if stage == "prep" else summaries[-1]["hashes"]
    for summary in summaries:
        summary["deterministic_vs_baseline"] = summary["hashes"] == baseline
    if stage == "prep":
        baseline_dir = ROOT / "results" / "prep" / "spawn1"
        reference = {
            asset_id: str(next(baseline_dir.glob(f".output-*/{asset_id}.jpg")))
            for asset_id in asset_ids
        }
        (ROOT / "prep-reference.json").write_text(json.dumps(reference))
    failures = _failure_probe(stage, asset_ids)
    (ROOT / f"{stage}-results.json").write_text(
        json.dumps({"runs": summaries, "failure_probe": failures}, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "deterministic": all(row["deterministic_vs_baseline"] for row in summaries),
                "failure_probe": failures,
            }
        )
    )


if __name__ == "__main__":
    main()
