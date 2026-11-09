"""旧7,607件の地形限定snapshot・統計・比較を私有領域へ別版生成する。"""

import hashlib
import json
from collections import Counter
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import duckdb
from bench.issue122.production import (
    BASELINE_TABLES,
    CODE,
    GATE,
    ROOT,
    baseline,
    database,
    read,
    save,
)
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from colorstats import privacy_review
from colorstats.queue import Queue
from colorstats.schema.models import Job, ProcessingRun, RuleStat
from colorstats.stats import aggregate as aggregate_handler
from colorstats.stats.aggregate_cli import load_settings
from colorstats.stats.region_quality import load as load_quality
from colorstats.stats.report import markdown, report
from colorstats.stats.snapshot import canonical, digest, execute, verify

OUTPUT = Path("/mnt/data/derived/stats/issue122-terrain-20261109-v1")
OLD = Path("/mnt/data/derived/stats/issue105-corrected-20261105T105836Z")
OLD_SNAPSHOT = "a8384373192d930df952190433d5d346393549b87c941ef157ea93380c714864"
REVIEW_SHA256 = "6dec63d6a6d0a93ec31969b8bbaaa5023aeb4037aa20df3e8195ad2e452a4fbf"


def preservation(db):
    counts = {}
    with db.connect() as connection:
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        for table in BASELINE_TABLES:
            before = read(ROOT / ("before-" + table + ".json"))
            after = baseline(connection, table)
            changed = sum(after.get(key) != value for key, value in before.items())
            counts[table] = {"before": len(before), "changed_or_missing": changed}
            if changed:
                raise ValueError("旧行が変更されています")
    return counts


def selection(db):
    plan = read(ROOT / "plan.json")
    records = {}
    for host in ("ubuntu1", "ubuntu2"):
        subset = read(ROOT / host / "records.json")
        assert not records.keys() & subset.keys()
        records.update(subset)
    expected = {row["asset_id"] for row in plan["rows"] if row["status"] == "ready"}
    if records.keys() != expected or not all(row.get("terminal") for row in records.values()):
        raise ValueError("全候補の本番B/Cが終結していません")
    review_bytes = (GATE / "review-freeze.json").read_bytes()
    if hashlib.sha256(review_bytes).hexdigest() != REVIEW_SHA256:
        raise ValueError("#129の人確認一覧の固定SHAが一致しません")
    review = json.loads(review_bytes)
    human_holds = {row["asset_id"] for row in review["records"]}
    rows, counts, stages = [], Counter(), Counter()
    with Session(db) as session:
        for row in plan["rows"]:
            aid = row["asset_id"]
            item = {"asset_id": aid, "status": row["status"]}
            if item["status"] == "ready":
                record = records[aid]
                for stage in ("segment", "shade", "color"):
                    if run_id := record.get(stage + "_run_id"):
                        job = session.scalar(select(Job).where(Job.run_id == UUID(run_id)))
                        if (job.status != "succeeded" or str(job.asset_id) != aid
                                or job.stage != stage):
                            raise ValueError("本番の成功stageとassetが一致しません")
                        stages[stage] += 1
                if record["privacy_verdict"]["decision"] != "accepted":
                    item["status"] = "privacy_pending"
                elif row["analysis_domain"] != "real_terrain":
                    item["status"] = "building_not_aggregated"
                elif aid in human_holds:
                    item["status"] = "human_reference_pending"
                else:
                    item.update(privacy_review.selection(session, aid,
                                                         record["privacy_review_run_id"]))
                    item.update({key: record[key] for key in (
                        "segment_run_id", "shade_run_id", "color_run_id")})
                    item["prep_run_id"] = row["input_run_id"]
                    item["status"] = "terrain_selected"
            counts[item["status"]] += 1
            rows.append(item)
    original = read(OLD / "selection.json")
    assert {row["asset_id"] for row in rows} == {row["asset_id"] for row in original["assets"]}
    return {"taxonomy_version": original["taxonomy_version"], "assets": rows,
            "subject_attribute_run_ids": original.get("subject_attribute_run_ids", []),
            "policy_version": "issue122-terrain-v1"}, {"states": counts, "stages": stages,
            "human_review": {"successor_issue": 114,
                             "held_missing_new_reference": counts["human_reference_pending"],
                             "file_sha256": REVIEW_SHA256,
                             "source_sha256": digest(review)}}


def summary(data, manifest):
    statuses = Counter(row["quality"]["status"] for row in data["rows"])
    roles = {}
    for row in data["rows"]:
        if row["conditions"] == {"domain": "real_terrain"} and len(row["target_parts"]) == 1:
            roles[row["target_parts"][0]] = {
                "sample_count": row["sample_count"], "subject_count": row["subject_count"],
                "n_eff": row["effective_sample_size"],
                **{key: row["quality"][key] for key in (
                    "status", "correction_rate", "no_information_rate", "flags")}}
    return {"snapshot_id": manifest["snapshot_id"], "policy": "issue122-terrain-v1",
            "counts": manifest["counts"], "exclusions": manifest["exclusions"],
            "statistics_rows": len(data["rows"]), "statuses": statuses,
            "supported": sum(statuses.get(key, 0) for key in ("direct", "smoothed")),
            "roles": roles, "building": "未集計", "building_fallback": False}


def ensure_snapshot(db, selected, quality):
    """完成済みを照合して再利用し、未完成出力は保全して別の試行先で再生成する。"""
    snapshot = OUTPUT / "snapshot"
    if (snapshot / "manifest.json").exists():
        manifest = read(snapshot / "manifest.json")
        verify(snapshot, manifest["snapshot_id"])
        assert manifest["selection_hash"] == digest(selected)
    else:
        attempt = (OUTPUT / ("snapshot-attempt-" + uuid4().hex)
                   if snapshot.exists() else snapshot)
        manifest = execute(db, selected, attempt, quality=quality,
                           code_version="issue122-terrain-v1-" + digest(quality)[:16])
        if attempt != snapshot:
            snapshot.rename(OUTPUT / ("snapshot-incomplete-" + uuid4().hex))
            attempt.rename(snapshot)
    return snapshot, manifest


def main():
    db = database()
    try:
        OUTPUT.mkdir(mode=0o700, parents=True, exist_ok=True)
        save(OUTPUT / "preserved-before.json", preservation(db))
        selected, execution = selection(db)
        selected_path = OUTPUT / "selection.json"
        if selected_path.exists():
            assert read(selected_path) == selected
        else:
            save(selected_path, selected)
        quality = load_quality(CODE)
        snapshot, manifest = ensure_snapshot(db, selected, quality)
        settings = load_settings(CODE / "configs/stats.yaml",
                                 CODE / "configs/collection_targets.yaml", CODE / "taxonomy")
        settings["strata"] = [row for row in settings["strata"]
                              if row["attributes"]["domain"] == "real_terrain"]
        payload = {"snapshot": str(snapshot), "snapshot_id": manifest["snapshot_id"],
                   "settings": settings, "output_path": str(OUTPUT / "aggregate/statistics.json")}
        queue = Queue(db, lease=timedelta(minutes=30), timeout=60)
        job_id = queue.enqueue("aggregate", None, aggregate_handler.config_hash(payload), payload)
        with Session(db) as session:
            job = session.get(Job, job_id)
            finished = job.status == "succeeded"
            run_id = job.run_id
        if not finished:
            claim = queue.claim(("aggregate",), job_ids=[job_id])
            if claim is None:
                raise RuntimeError("集計jobを取得できません")
            try:
                prepared = aggregate_handler.prepare(claim)
                queue.renew(claim)
                run_id = queue.complete(
                    claim, prepared.info,
                    lambda session, run: aggregate_handler.register(session, run, prepared.data),
                    prepared.files)
            except BaseException as error:
                queue.fail(claim, type(error).__name__)
                raise
        with Session(db) as session:
            run = session.get(ProcessingRun, run_id)
            data = read(Path(next(iter(run.output_paths.values()))))
            actual = session.scalars(select(RuleStat).where(
                RuleStat.processing_run_id == run_id)).all()
            registered = [{key: getattr(row, key) for key in data["rows"][0]} for row in actual]
            assert sorted(map(canonical, registered)) == sorted(map(canonical, data["rows"]))
        assert all(row["conditions"]["domain"] == "real_terrain" and
                   set(row["target_parts"]) <= {"tree", "water"} for row in data["rows"])
        result = summary(data, manifest)
        rendered = report(snapshot, manifest["snapshot_id"], data, settings)
        rendered["issue122_scope"] = {"roles": ["water", "tree"], "building": "未集計",
                                      "human_review": execution["human_review"]}
        save(OUTPUT / "report/report.json", rendered)
        (OUTPUT / "report/report.md").write_text(
            "# #122 地形側の訂正版基準\n\n建物側は未集計。\n\n" + markdown(rendered),
            encoding="utf-8")
        old_manifest = read(OLD / "snapshot/manifest.json")
        verify(OLD / "snapshot", OLD_SNAPSHOT)
        old_report = read(OLD / "report/report.json")
        old_registration = read(OLD / "aggregate/registration.json")
        sources = {}
        with duckdb.connect() as connection:
            for name, root in (("old", OLD), ("new", OUTPUT)):
                sources[name] = dict(connection.execute(
                    "SELECT coalesce(json_extract_string(a.data,'$.search_provider'),"
                    "json_extract_string(p.data,'$.site')),count(*) "
                    "FROM read_parquet(?) a JOIN read_parquet(?) p ON a.id=p.asset_id "
                    "WHERE a.eligible GROUP BY 1", [str(root / "snapshot/assets.parquet"),
                                                   str(root / "snapshot/provenance.parquet")],
                ).fetchall())
        checks = {row["condition"]: row for row in rendered["m3_checks"]}
        old_checks = {row["condition"]: row for row in old_report["m3_checks"]}
        comparison = {"old_snapshot_id": old_manifest["snapshot_id"], "new": result,
                      "old_counts": old_manifest["counts"],
                      "old_supported": old_registration["supported"],
                      "old_roles": old_registration["condition4"],
                      "condition4": {"old": old_checks[4], "new": checks[4]},
                      "eligible_sources": sources, "execution": execution,
                      "registration": {"job_id": str(job_id), "run_id": str(run_id)},
                      "preserved": preservation(db),
                      "m4": {"automatic_alias_update": False, "release": False,
                             "building": "未集計", "selection_required": True}}
        save(OUTPUT / "comparison.json", comparison)
        save(OUTPUT / "summary.json", result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        db.dispose()


if __name__ == "__main__":
    main()
