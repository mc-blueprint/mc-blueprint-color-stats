"""Issue #66 の固定コホートを既存 Queue/Worker で実行・照合する。

DATABASE_URL は環境からだけ取得する。freeze は新規 manifest を作り、
run はその入力・設定・コードを照合して未完了ジョブだけを進める。
report は DB と不変 artifact を読み取り、全量完了後も同じ方法で集計する。
"""

import argparse
import json
import os
import signal
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import yaml
from bench.issue47.benchmark import Sampler
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from colorstats.analyze import segment
from colorstats.queue.core import Queue
from colorstats.queue.worker import Worker
from colorstats.schema.models import Asset, Job, ProcessingRun, ProcessingRunInput

STAGES = ("segment", "shade", "color")
ROOT = Path(__file__).resolve().parents[2]


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str,
                               allow_nan=False) + "\n", encoding="utf-8")


def implementation():
    paths = sorted((ROOT / "src/colorstats").rglob("*.py"))
    paths += sorted((ROOT / "src/colorstats/analyze").glob("oneformer-*.json"))
    paths += sorted((ROOT / "src/colorstats/analyze").glob("region-parents-*.json"))
    paths += [Path(__file__), ROOT / "configs/segment_stats.yaml"]
    return {str(p.relative_to(ROOT)): segment._hash(p) for p in paths}


def _check_policy_reuse(source, settings):
    from colorstats.analyze.region_policy import METHOD, policy_hash
    from colorstats.analyze.visible_wall import METHOD as WALL_METHOD
    from colorstats.analyze.visible_wall import policy_hash as wall_hash

    method = settings["segment"]["method"]
    if method not in (METHOD, WALL_METHOD):
        return
    payload = source.parameters.get("payload", {})
    if (source.parameters.get("region_policy_hash") != (
            wall_hash() if method == WALL_METHOD else policy_hash())
            or any(payload.get(k) != v for k, v in settings["segment"].items())
            or segment.config_hash(payload) != source.config_hash):
        raise ValueError("新policyで旧segmentや異なる入力・モデル・promptは再利用できません")


def freeze(engine, root, asset_ids=None, *, reuse_segments=False, settings_path=None):
    """指定assetの完了prepと入力hashを新規固定する。省略時は#66固定全量を検査する。

    asset_idsは重複のないUUID一覧。欠落・未完了prep・既存manifestは拒否する。
    DBは読取り専用で、成功prep出力を後続GPU処理の不変入力とする。
    reuse_segmentsは同じprepと画像hashの成功segmentを固定し、後続だけを新規実行する。
    人物判定があればそのSHAとperson_maskも固定する。
    settings_pathはfreezeする別設定YAML。省略時は既存の採用設定を使う。
    """
    settings = yaml.safe_load((settings_path or ROOT / "configs/segment_stats.yaml").read_text(
        encoding="utf-8",
    ))
    if asset_ids is not None:
        identifiers = [UUID(value) for value in asset_ids]
        if not identifiers or len(set(identifiers)) != len(identifiers):
            raise ValueError("cohortは空でない重複なしのasset ID一覧が必要です")
    with Session(engine) as session:
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        query = select(Asset).order_by(Asset.id)
        if asset_ids is not None:
            query = query.where(Asset.id.in_(identifiers))
        assets = session.scalars(query).all()
        if asset_ids is not None and len(assets) != len(identifiers):
            raise ValueError("cohortに存在しないasset IDがあります")
        rows = []
        for asset in assets:
            job = session.scalar(select(Job).where(
                Job.asset_id == asset.id, Job.stage == "prep",
            ).order_by((Job.status == "succeeded").desc(), Job.created_at.desc()).limit(1))
            if job is None:
                raise ValueError("prep job がない asset があります")
            row = {"asset_id": str(asset.id), "sha256": asset.sha256,
                   "license_class": asset.license_class, "taxonomy_version": asset.taxonomy_version,
                   "prep_status": job.status, "prep_reason": job.failure_reason}
            review = asset.quality.get("privacy_review")
            if review:
                row.update(person_mask=review.get("person_mask"),
                           privacy_review_sha256=segment._digest(review))
            if job.status == "succeeded":
                run = session.get(ProcessingRun, job.run_id)
                if run.finished_at is None or run.failure_reason or run.stage != "prep":
                    raise ValueError("成功 prep の run が不正です")
                paths = list(run.output_paths.values())
                if len(paths) != 1:
                    raise ValueError("prep の画像出力は1件である必要があります")
                row.update(input_run_id=str(run.id), input_path=paths[0],
                           input_sha256=segment._hash(paths[0]),
                           input_bytes=Path(paths[0]).stat().st_size)
                if reuse_segments:
                    previous = session.scalar(select(Job).where(
                        Job.asset_id == asset.id, Job.stage == "segment", Job.status == "succeeded",
                        Job.payload["input_run_id"].astext == str(run.id),
                        Job.payload["input_sha256"].astext == row["input_sha256"],
                    ).order_by(Job.created_at.desc()).limit(1))
                    if previous is None:
                        raise ValueError("再利用できる成功segmentがありません")
                    source = session.get(ProcessingRun, previous.run_id)
                    if source.finished_at is None or source.failure_reason:
                        raise ValueError("再利用segmentのrunが未確定です")
                    _check_policy_reuse(source, settings)
                    row["segment_run_id"] = str(source.id)
            elif job.status != "failed":
                raise ValueError("prep が未完了です")
            rows.append(row)
    if asset_ids is None and (
        len(rows) != 7607 or sum(r["prep_status"] == "succeeded" for r in rows) != 7603
    ):
        raise ValueError("固定7,607件・成功prep7,603件のコホートと一致しません")
    manifest = {"created_at": datetime.now(UTC).isoformat(), "assets": rows,
                "settings": settings, "implementation": implementation()}
    with (root / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"assets": len(rows), "prep": dict(Counter(r["prep_status"] for r in rows)),
                      "manifest_sha256": segment._hash(root / "manifest.json")}), flush=True)


def snapshot(engine):
    """表・索引・WAL のDB全体値。並行書込みを含むため専有増分とは扱わない。"""
    with engine.connect() as connection:
        result = dict(connection.execute(text("""
            SELECT clock_timestamp() AS at, pg_current_wal_lsn()::text AS wal_lsn,
                   pg_database_size(current_database()) AS database_bytes
        """)).mappings().one())
        result["tables"] = [dict(r) for r in connection.execute(text("""
            SELECT relname, pg_table_size(relid) AS table_bytes,
                   pg_indexes_size(relid) AS index_bytes, n_tup_ins,n_tup_upd,n_tup_del
            FROM pg_stat_user_tables ORDER BY relname
        """)).mappings()]
        result["indexes"] = [dict(r) for r in connection.execute(text("""
            SELECT indexrelname,pg_relation_size(indexrelid) AS bytes
            FROM pg_stat_user_indexes ORDER BY indexrelname
        """)).mappings()]
        return result


def io_counters(worker):
    """親と生存中の計算子の論理I/O・物理I/O byte。子の交代は別PIDで区別する。"""
    pids = [os.getpid()]
    if worker._process is not None and worker._process.is_alive():
        pids.append(worker._process.pid)
    result = {}
    for pid in pids:
        try:
            result[str(pid)] = dict(
                (key.rstrip(":"), int(value))
                for key, value in (line.split() for line in Path(f"/proc/{pid}/io").read_text()
                                   .splitlines())
            )
        except FileNotFoundError:
            continue
    return result


def _process_io_bytes(attempts):
    keys = ("rchar", "wchar", "read_bytes", "write_bytes")
    snapshots = [attempt["io"] for attempt in attempts if attempt.get("io")]
    initial = next((attempt["io"] for attempt in attempts
                    if attempt["event"] == "started" and attempt.get("io")), {})
    initial_total = {key: sum(values.get(key, 0) for values in initial.values())
                     for key in keys}
    maximum = dict(initial_total)
    for snapshot in snapshots:
        for key in keys:
            total = sum(values.get(key, 0) for values in snapshot.values())
            maximum[key] = max(maximum[key], total)
    return {key: maximum[key] - initial_total[key] for key in keys}


def append(root, record):
    with (root / "attempts.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def run_batch(engine, root, manifest, models, limit):
    """対象ジョブだけを既存Workerで実行。停止後も同じmanifestで冪等に再開する。"""
    import fcntl

    from colorstats.analyze import color, shade
    from colorstats.analyze.region_policy import METHOD, OOM_REASON
    from colorstats.analyze.visible_wall import METHOD as WALL_METHOD

    lock = (root / "runner.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if manifest["implementation"] != implementation():
        raise ValueError("固定したコード・採用設定が変わっています")
    stop = root / "stop"
    if stop.exists():
        raise ValueError("stop ファイルを確認して取り除いてから再開してください")
    signal.signal(signal.SIGTERM, lambda *_: stop.touch())
    signal.signal(signal.SIGINT, lambda *_: stop.touch())
    batch = segment._hash(root / "manifest.json")
    queue = Queue(engine, timeout=60)
    handlers = {s: f"colorstats.analyze.{s}" for s in STAGES}
    worker = Worker(queue, handlers, stop)
    invocation = uuid4().hex
    before_path = root / f"{invocation}-before.json"
    save(before_path, snapshot(engine))
    started = time.monotonic()
    save(root / f"{invocation}-session.json", {
        "before": before_path.name, "after": None, "elapsed_seconds": 0,
        "interrupted": True,
    })
    processed = 0
    try:
        with Sampler(root / f"{invocation}-telemetry.jsonl"):
            for row in manifest["assets"]:
                if stop.exists() or (limit is not None and processed >= limit):
                    break
                if row["prep_status"] != "succeeded":
                    continue
                base = {key: row[key] for key in (
                    "input_path", "input_run_id", "input_sha256",
                    "license_class", "taxonomy_version",
                )}
                base["batch"] = batch
                if "person_mask" in row:
                    base["person_mask"] = row["person_mask"]
                if row.get("privacy_review_sha256"):
                    with Session(engine) as session:
                        review = session.get(Asset, UUID(row["asset_id"])).quality["privacy_review"]
                        if segment._digest(review) != row["privacy_review_sha256"]:
                            raise ValueError("固定後に人物判定が変わっています")
                region_run = UUID(row["segment_run_id"]) if row.get("segment_run_id") else None
                if region_run is not None:
                    with Session(engine) as session:
                        _check_policy_reuse(session.get(ProcessingRun, region_run),
                                            manifest["settings"])
                for stage in STAGES:
                    if stage == "segment" and row.get("segment_run_id"):
                        continue
                    if stop.exists():
                        break
                    payload = {**base, "output_path": str(root / "outputs" /
                                                          f'{row["asset_id"]}-{stage}.json')}
                    handler = {"segment": segment, "shade": shade, "color": color}[stage]
                    if stage == "segment":
                        payload.update(manifest["settings"]["segment"])
                        components = ("sam2", "dino")
                        if payload["method"] in (METHOD, WALL_METHOD):
                            components += ("oneformer",)
                        payload["model_paths"] = {n: str(models / n) for n in components}
                    else:
                        with Session(engine) as session:
                            payload["regions"] = color.region_inputs(
                                session, UUID(row["asset_id"]), region_run,
                            )
                            policy = color.region_policy_input(
                                session, UUID(row["asset_id"]), region_run,
                            )
                            if policy is not None:
                                payload["region_policy"] = policy
                        payload["region_run_id"] = str(region_run)
                        if stage == "shade":
                            payload.update(manifest["settings"]["shade"])
                    try:
                        config = handler.config_hash(payload)
                    except (ValueError, OSError) as error:
                        append(root, {"event": "input_rejected", "asset_id": row["asset_id"],
                                      "stage": stage, "reason": str(error),
                                      "at": datetime.now(UTC)})
                        break
                    job_id = queue.enqueue(stage, UUID(row["asset_id"]), config, payload)
                    while not stop.exists():
                        with Session(engine) as session:
                            job = session.get(Job, job_id)
                            if job.status in {"succeeded", "failed"}:
                                break
                        claim = queue.claim((stage,), job_ids=(job_id,))
                        if claim is None:
                            time.sleep(1)
                            continue
                        attempt_start = time.monotonic()
                        append(root, {"event": "started", "job_id": str(job_id),
                                      "token": str(claim.token), "attempt": claim.attempt,
                                      "stage": stage, "at": datetime.now(UTC),
                                      "io": io_counters(worker)})
                        worker._run_claim(claim)
                        with Session(engine) as session:
                            job = session.get(Job, job_id)
                            append(root, {"event": "finished", "job_id": str(job_id),
                                          "token": str(claim.token), "attempt": claim.attempt,
                                          "stage": stage, "status": job.status,
                                          "reason": job.failure_reason,
                                          "seconds": time.monotonic() - attempt_start,
                                          "at": datetime.now(UTC), "io": io_counters(worker)})
                            if (payload.get("method") in (METHOD, WALL_METHOD)
                                    and OOM_REASON in (job.failure_reason or "")):
                                stop.touch()
                    with Session(engine) as session:
                        job = session.get(Job, job_id)
                        if job.status != "succeeded":
                            break
                        if stage == "segment":
                            region_run = job.run_id
                processed += 1
                print(json.dumps({"processed": processed, "asset_id": row["asset_id"],
                                  "elapsed_seconds": time.monotonic() - started}), flush=True)
    finally:
        worker._stop_prepare()
        save(root / f"{invocation}-after.json", snapshot(engine))
        save(root / f"{invocation}-session.json", {
            "before": before_path.name, "after": f"{invocation}-after.json",
            "elapsed_seconds": time.monotonic() - started,
            "stopped": stop.exists(), "processed": processed,
        })
        lock.close()


def report(engine, root, manifest, output):
    """成功run・由来・権利・artifactと試行を照合し、新規JSONへ再集計する。"""
    from colorstats.analyze import color

    batch = segment._hash(root / "manifest.json")
    assets = {r["asset_id"]: r for r in manifest["assets"]}
    stages = {}
    violations = []
    artifacts = {}
    successful_assets = {}
    with Session(engine) as session:
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        jobs = session.scalars(select(Job).where(Job.payload["batch"].astext == batch)).all()
        reused = [UUID(row["segment_run_id"]) for row in assets.values()
                  if row.get("segment_run_id")]
        if reused:
            jobs.extend(session.scalars(select(Job).where(
                Job.stage == "segment", Job.status == "succeeded", Job.run_id.in_(reused),
            )).all())
        for stage in STAGES:
            selected = [j for j in jobs if j.stage == stage]
            successful = [j for j in selected if j.status == "succeeded"]
            successful_assets[stage] = {str(j.asset_id) for j in successful}
            stages[stage] = {
                "jobs": len(selected), "status": dict(Counter(j.status for j in selected)),
                "attempts": sum(j.attempts for j in selected),
                "retries": sum(max(0, j.attempts - 1) for j in selected),
                "failures": [{"asset_id": str(j.asset_id), "reason": j.failure_reason}
                             for j in selected if j.status == "failed"],
                "successful_run_seconds": 0, "input_bytes": 0, "output_bytes": 0,
                "regions": 0, "part_observations": 0, "relations": 0,
            }
            for job in successful:
                run = session.get(ProcessingRun, job.run_id)
                row = assets[str(job.asset_id)]
                source = session.get(ProcessingRun, UUID(row["input_run_id"]))
                payload = job.payload
                links = set(session.scalars(select(ProcessingRunInput.input_run_id).where(
                    ProcessingRunInput.run_id == run.id,
                )))
                expected_links = {source.id}
                if stage != "segment":
                    region_run = UUID(payload["region_run_id"])
                    expected_links.add(region_run)
                    if payload["regions"] != color.region_inputs(session, job.asset_id, region_run):
                        violations.append(f"{run.id}:regions")
                    if payload.get("region_policy") != color.region_policy_input(
                        session, job.asset_id, region_run,
                    ):
                        violations.append(f"{run.id}:region_policy")
                licenses = [row["license_class"], source.license_class]
                if stage != "segment":
                    licenses.append(session.get(ProcessingRun, region_run).license_class)
                if (run.finished_at is None or run.failure_reason or run.stage != stage
                        or run.config_hash != job.stage_config_hash or links != expected_links
                        or payload["input_path"] not in source.output_paths.values()
                        or payload["input_sha256"] != row["input_sha256"]
                        or run.license_class != segment._license(*licenses)
                        or segment._hash(row["input_path"]) != row["input_sha256"]):
                    violations.append(f"{run.id}:provenance")
                data = None
                for path in run.output_paths.values():
                    p = Path(path)
                    artifacts[path] = segment._hash(p)
                    stages[stage]["output_bytes"] += p.stat().st_size
                    if p.suffix == ".json":
                        data = json.loads(p.read_text())
                stages[stage]["input_bytes"] += row["input_bytes"]
                stages[stage]["successful_run_seconds"] += (
                    run.finished_at - run.started_at).total_seconds()
                if stage == "segment":
                    count = session.scalar(text(
                        "SELECT count(*) FROM region WHERE processing_run_id=:id"), {"id": run.id})
                    stages[stage]["regions"] += count
                    if count != len(data["regions"]):
                        violations.append(f"{run.id}:region_count")
                else:
                    observed = session.scalar(text(
                        "SELECT count(*) FROM color_observation "
                        "WHERE processing_run_id=:id AND region_id IS NOT NULL"), {"id": run.id})
                    related = session.scalar(text(
                        "SELECT count(*) FROM relation WHERE processing_run_id=:id"),
                        {"id": run.id})
                    stages[stage]["part_observations"] += observed
                    stages[stage]["relations"] += related
                    if (observed != sum(len(r["observations"]) for r in data["regions"])
                            or related != len(data["relations"])):
                        violations.append(f"{run.id}:observation_count")
                    if stage == "color":
                        registered = [dict(r) for r in session.execute(text(
                            "SELECT region_a::text,region_b::text,type,delta_l,delta_c,delta_h,"
                            "delta_e_ok,area_ratio FROM relation WHERE processing_run_id=:id "
                            "ORDER BY region_a,region_b"), {"id": run.id}).mappings()]
                        if registered != data["relations"]:
                            violations.append(f"{run.id}:registered_relations")
                        if data["relations"] != color.extract_relations(data["regions"]):
                            violations.append(f"{run.id}:relation_sign")
        sessions = [json.loads(p.read_text()) for p in sorted(root.glob("*-session.json"))]
        deltas = []
        for item in sessions:
            before = json.loads((root / item["before"]).read_text())
            after = (json.loads((root / item["after"]).read_text())
                     if item["after"] else snapshot(engine))
            wal = session.scalar(text("SELECT pg_wal_lsn_diff(:after,:before)"),
                                 {"after": after["wal_lsn"], "before": before["wal_lsn"]})
            tables = {t["relname"]: t for t in before["tables"]}
            indexes = {t["indexrelname"]: t["bytes"] for t in before["indexes"]}
            deltas.append({
                "session": item, "database_bytes": after["database_bytes"]-before["database_bytes"],
                "wal_bytes": int(wal), "includes_concurrent_writes": True,
                "tables": {t["relname"]: {k: t[k]-tables.get(t["relname"], {}).get(k, 0)
                                        for k in ("table_bytes", "index_bytes")}
                           for t in after["tables"]},
                "indexes": {t["indexrelname"]: t["bytes"]-indexes.get(t["indexrelname"], 0)
                            for t in after["indexes"]},
            })
    attempts_path = root / "attempts.jsonl"
    attempts = [json.loads(line) for line in attempts_path.read_text().splitlines()] \
        if attempts_path.exists() else []
    finished = [a for a in attempts if a["event"] == "finished"]
    telemetry = []
    for path in sorted(root.glob("*-telemetry.jsonl")):
        telemetry.extend(json.loads(line) for line in path.read_text().splitlines())
    io = _process_io_bytes(attempts)
    completed = successful_assets["color"]
    elapsed = sum(s["elapsed_seconds"] for s in sessions)
    result = {
        "manifest_sha256": batch, "assets": len(assets),
        "sha256_unique": len({r["sha256"] for r in assets.values()}),
        "prep_failed": [r for r in assets.values() if r["prep_status"] == "failed"],
        "stages": stages, "completed_assets": len(completed),
        "jobs": [{"asset_id": str(j.asset_id), "stage": j.stage, "job_id": str(j.id),
                  "run_id": str(j.run_id) if j.run_id else None, "status": j.status,
                  "reason": j.failure_reason, "attempts": j.attempts}
                 for j in jobs],
        "process_io_bytes": io,
        "io_note": "各snapshotで親と稼働中の子を合算し、親へ取り込まれた終了子の値は再加算しない。",
        "telemetry": {
            "samples": len(telemetry),
            "gpu_utilization_mean_percent": (
                sum(t["gpu_utilization_percent"] for t in telemetry)/len(telemetry)
                if telemetry else None),
            "gpu_memory_max_mib": max((t["gpu_memory_mib"] for t in telemetry), default=None),
        },
        "pending_assets": (sum(r["prep_status"] == "succeeded" for r in assets.values())
                           - len(completed)),
        "violations": violations, "artifacts": artifacts, "db_deltas": deltas,
        "elapsed_seconds": elapsed,
        "completed_per_elapsed_second": len(completed)/elapsed if elapsed else None,
        "attempt_events": dict(Counter(a["event"] for a in attempts)),
        "failed_attempt_seconds": sum(a["seconds"] for a in finished if a["status"] != "succeeded"),
        "successful_attempt_seconds": sum(a["seconds"] for a in finished
                                          if a["status"] == "succeeded"),
        "input_rejections": [a for a in attempts if a["event"] == "input_rejected"],
        "unclosed_attempts": len({a["token"] for a in attempts if a["event"] == "started"}
                                - {a["token"] for a in finished}),
        "quality": manifest["settings"]["quality"],
        "note": "全体colorは完了数に含めない。子ラベルは診断用。和集合統計は後続snapshotで生成。",
    }
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, default=str)
        stream.write("\n")
    print(json.dumps({k: result[k] for k in (
        "completed_assets", "pending_assets", "violations", "elapsed_seconds",
    )}), flush=True)
    return result


def main(engine=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "run", "report"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--models", type=Path, default=Path("/mnt/data/work/issue-40/models"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--asset-ids", type=Path,
                        help="freeze対象のUUID一覧JSON。省略は#66固定全量")
    parser.add_argument("--reuse-segments", action="store_true",
                        help="freeze時に同じprep入力の成功segmentを固定して再利用")
    parser.add_argument("--settings", type=Path,
                        help="freeze時の設定。新policyは既存の採用設定とは別ファイルで指定")
    args = parser.parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "outputs").mkdir(exist_ok=True)
    if engine is None:
        engine = create_engine(os.environ["DATABASE_URL"], echo=False, hide_parameters=True)
    try:
        if args.action == "freeze":
            freeze(engine, root, json.loads(args.asset_ids.read_text()) if args.asset_ids else None,
                   reuse_segments=args.reuse_segments, settings_path=args.settings)
        else:
            manifest = json.loads((root / "manifest.json").read_text())
            if args.action == "run":
                run_batch(engine, root, manifest, args.models.resolve(), args.limit)
            else:
                if args.output is None:
                    parser.error("report には新規 --output が必要です")
                result = report(engine, root, manifest, args.output)
                if result["violations"]:
                    raise ValueError(f"report integrity violations: {len(result['violations'])}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"処理失敗: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
