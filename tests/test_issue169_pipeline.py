"""両freeze・再開・目視追記から実snapshot/aggregate/reportまでを隔離DBで通す。"""

import copy
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from bench.issue114 import mobile, terrain_statistics
from bench.issue114 import production as terrain
from bench.issue122 import production, runtime, statistics
from PIL import Image
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from colorstats import image_gate, privacy_review, retention
from colorstats.analyze import color, region_policy, shade
from colorstats.schema.models import Asset, Job, ProcessingRun, Source
from colorstats.stats import aggregate, region_quality, snapshot
from colorstats.stats.aggregate_cli import load_settings
from colorstats.stats.report import report
from tests import test_privacy_review_db as privacy_fixtures
from tests import test_region_policy as region_fixtures
from tests import test_region_policy_db as policy_fixtures
from tests import test_segment as segment_fixtures
from tests import test_segment_db as prep_fixtures
from tests.test_queue import database as database
from tests.test_queue import queue as queue

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="隔離DB専用")


def test_両freezeから再開と目視を経て旧のみと比較の実統計を生成する(queue, tmp_path, monkeypatch):
    repository = Path(__file__).resolve().parents[1]
    code = tmp_path / "code"
    for name in ("taxonomy", "configs", "bench/issue121", "bench/issue73"):
        shutil.copytree(repository / name, code / name)
    prompts = production.read(code / "bench/issue73/plan.json")["source_settings"]["ade"]["prompts"]
    source_id = uuid4()
    with Session(queue.engine) as session, session.begin():
        session.add(Source(id=source_id, url="https://example.test/pipeline", site="fixture",
                           author="合成", attribution="合成・CC0", license="cc0",
                           license_class="open", retrieved_at=datetime.now(UTC), policy={}))
    rows, gates, models = [], {}, None
    for index in range(6):
        aid = uuid4()
        with Session(queue.engine) as session, session.begin():
            session.add(Asset(id=aid, source_id=source_id, url=f"https://example.test/{index}",
                              sha256="a" * 64, storage_path="synthetic", domain="real_terrain",
                              license_class="open", retrieved_at=datetime.now(UTC),
                              taxonomy_version="0.1.0", scene_attributes={}, quality={}))
        directory = tmp_path / f"source-{index}"
        directory.mkdir()
        payload = segment_fixtures.payload.__wrapped__(directory)
        payload = region_fixtures.regional_payload.__wrapped__(payload, monkeypatch)
        payload.update(threshold=0.35, text_threshold=0.25, prompts=prompts)
        prep = prep_fixtures.prep_source.__wrapped__(queue, aid, payload)
        policy = policy_fixtures.policy_source.__wrapped__(queue, aid, payload, prep, monkeypatch)
        new_image = Image.new
        verdict = privacy_fixtures.verdict

        def distinct_image(*args, new_image=new_image, index=index, **kwargs):
            image = new_image(*args, **kwargs)
            if image.mode == "RGB" and image.size == (128, 64):
                image.putpixel((0, 0), (index, 10, 20))
            return image

        with monkeypatch.context() as patch:
            patch.setattr(Image, "new", distinct_image)
            patch.setattr(privacy_fixtures, "verdict",
                          lambda verdict=verdict, **k: verdict(subject="terrain", **k))
            source, gate, sha = privacy_fixtures.review_source.__wrapped__(
                queue, aid, policy, directory, SimpleNamespace())
        with Session(queue.engine) as session, session.begin():
            asset = session.get(Asset, aid)
            asset.quality = {"privacy_review": {"decision": "accepted"}, "license": "cc0",
                             "author": "合成", "license_url": "https://example.test/license"}
            retention.register_asset(session, asset, {}, "fixture")
            job = session.scalar(select(Job).where(Job.run_id == gate))
            gates[str(aid)] = str(job.id)
        rows.append({**source, "asset_id": str(aid), "sha256": sha,
                     "prep_status": "succeeded", "image_gate_run_id": str(gate)})
        models = Path(payload["model_paths"]["dino"]).parent

    with Session(queue.engine) as session:
        segment = session.get(ProcessingRun, UUID(rows[-1]["region_run_id"]))
        parameters = copy.deepcopy(segment.parameters)
    frozen = production.read(code / "bench/issue121/freeze.json")
    frozen.update(policy_hash=parameters["region_policy_hash"],
                  oneformer=parameters["models"]["oneformer"],
                  models={k: parameters["models"][k]["files"] for k in ("sam2", "dino")})
    production.save(code / "bench/issue121/freeze.json", frozen)
    monkeypatch.setattr(region_quality, "FREEZE_DIGEST", snapshot.digest(frozen))
    # 重みは合成だが、モデル/prompt/maskの照合と品質方針は実処理を通す。
    for module in (production, terrain, statistics):
        monkeypatch.setattr(module, "CODE", code)
    monkeypatch.setattr(production, "implementation", production.implementation)
    monkeypatch.setattr(statistics, "database", lambda: queue.engine)
    monkeypatch.setattr(terrain_statistics, "database", lambda: queue.engine)
    for name in ("ROOT", "OLD", "OLD_SNAPSHOT", "OUTPUT", "POLICY", "selection"):
        monkeypatch.setattr(statistics, name, getattr(statistics, name))
    monkeypatch.setattr(production.subprocess, "check_output", lambda *a, **k: b"")
    monkeypatch.setattr(production, "Worker",
                        lambda *a: SimpleNamespace(_stop_prepare=lambda: None))

    def execute(q, worker, stage, row, payload):
        assert stage != "segment"
        handler = {"shade": shade, "color": color}[stage]
        job = q.enqueue(stage, row["asset_id"], handler.config_hash(payload), payload)
        claim = q.claim((stage,), job_ids=[job])
        q.check_input(claim)
        prepared = handler.prepare(claim)
        return str(q.complete(claim, prepared.info,
                              lambda s, r: handler.register(s, r, prepared.data), prepared.files))

    monkeypatch.setattr(production, "execute_job", execute)
    cohorts = {"old": rows[:3], "new": rows[3:]}
    filler = []
    for cohort, size in (("old", 7607), ("new", 2600)):
        for index in range(size - 3):
            aid = uuid4()
            held = cohort == "new" and index < 993
            filler.append({"id": aid, "source_id": source_id,
                           "url": f"https://example.test/{aid}", "sha256": "f" * 64,
                           "storage_path": "unused", "domain": "real_terrain",
                           "license_class": "open", "retrieved_at": datetime.now(UTC),
                           "taxonomy_version": "0.1.0", "scene_attributes": {},
                           "quality": {"privacy_review": {
                               "decision": "pending" if held else "accepted"}}})
            cohorts[cohort].append({"asset_id": str(aid), "sha256": "f" * 64,
                                    "prep_status": "failed"})
    with queue.engine.begin() as connection:
        connection.execute(insert(Asset), filler)
    held = tmp_path / "legacy-holds.json"
    production.save(held, {"asset_ids": [r["asset_id"] for r in cohorts["old"][3:113]],
                          "proof": {"human_runs_written": 0, "missing_references": 110}})
    monkeypatch.setattr(terrain, "LEGACY_HUMAN_HOLDS", {
        "path": str(held), "sha256": production.segment._hash(held)})
    gate_root = tmp_path / "gate"
    production.save(gate_root / "public-summary.json",
                    {"complete": True, "regression_passed": True})
    production.save(gate_root / "plan.json", {"identity": image_gate.identity(b""), "holds": [],
        "jobs": gates, "cohorts": {k: [r["asset_id"] for r in v] for k, v in cohorts.items()}})
    for module in (production, terrain, statistics):
        monkeypatch.setattr(module, "GATE", gate_root)
    production.save(gate_root / "review-freeze.json", {"records": []})
    monkeypatch.setattr(statistics, "REVIEW_SHA256",
                        production.segment._hash(gate_root / "review-freeze.json"))
    original = tmp_path / "original"
    production.save(original / "ubuntu1/manifest.json", {"assets": cohorts["new"]})
    production.save(original / "ubuntu2/manifest.json", {"assets": []})
    old_manifest = tmp_path / "old-manifest.json"
    production.save(old_manifest, {"assets": cohorts["old"]})
    monkeypatch.setattr(production, "OLD", old_manifest)
    monkeypatch.setattr(terrain, "ORIGINAL", original)
    sampling = {"seed": 169, "population_sha256": "a" * 64, "criteria": {"max_problems": 0},
                "required_ids": [r["asset_id"] for r in rows]}
    roots = {k: tmp_path / (k + "-restart") for k in cohorts}
    frozen_files = {}
    for cohort, module in (("old", production), ("new", terrain)):
        reuse = tmp_path / (cohort + "-reuse")
        production.save(reuse / "plan.json", {"partitions": [runtime.PARTITION]})
        production.save(reuse / "ubuntu1/records.json", {
            r["asset_id"]: {"segment_run_id": r["region_run_id"], "terminal": True}
            for r in cohorts[cohort][:3]})
        monkeypatch.setattr(module, "ROOT", roots[cohort])
        module.freeze(queue.engine, human_sampling=sampling, reuse_from=reuse, models=models)
        plan = runtime.read_plan(roots[cohort])
        assert plan["partitions"] == [runtime.PARTITION] and len(plan["reused_segments"]) == 3
        for name in ("plan.json", "execution.json"):
            path = roots[cohort] / name
            frozen_files[path] = path.read_bytes()
        if cohort == "new":
            terrain.configure()
        production.run(queue.engine, runtime.PARTITION, models, 1)
        assert len(production.read(roots[cohort] / "ubuntu1/records.json")) == 1
        production.run(queue.engine, runtime.PARTITION, models, None)
        assert len(production.read(roots[cohort] / "ubuntu1/records.json")) == 3

    decisions = []
    for row in rows:
        root = roots["old"] if row in rows[:3] else roots["new"]
        record = production.read(root / "ubuntu1/records.json")[row["asset_id"]]
        with Session(queue.engine) as session:
            selected = privacy_review.selection(session, row["asset_id"],
                                                 record["privacy_review_run_id"])
            policy = region_policy.reference(session.get(ProcessingRun, UUID(row["region_run_id"])))
        decisions.append({"asset_id": row["asset_id"], "selection": selected,
                          "input_path": row["input_path"], "input_sha256": row["input_sha256"],
                          "mask_path": policy["exclusions"]["person"]["path"],
                          "mask_sha256": policy["exclusions"]["person"]["sha256"],
                          "decision": "accepted", "subject": "terrain",
                          "reason": "person_not_detected",
                          "person_ratio": 0.0, "mask_ratio": 0.0})
    bundle, execution, human = (tmp_path / name for name in ("bundle", "presentation", "human"))
    production.save(execution / "privacy-decisions.json", decisions)
    manifest = {"sampling": sampling, "required_ids": sampling["required_ids"],
                "random_ids": sampling["required_ids"], "boundary_ids": [], "population": 6,
                "decisions_sha256": production.segment._hash(execution / "privacy-decisions.json"),
                "rows": [{k: v for k, v in row.items() if k in {
                    "asset_id", "input_sha256", "decision", "subject", "reason",
                    "person_ratio", "mask_ratio"}} for row in decisions]}
    production.save(bundle / "manifest.json", manifest)
    production.save(execution / "review-manifest.json", manifest)
    mobile.build(queue.engine, bundle, execution, human, repository / "taxonomy")
    production.save(human / "review-manifest.json", manifest)
    reply = mobile.reply_reviews(production.read(human / "number-map.json"),
                                 human / "review-manifest.json", manifest["decisions_sha256"],
                                 "全6枚確認済み\n問題なし", directory=human)
    production.save(human / "converted-review.json", mobile.apply_privacy_reply(queue, reply))
    for cohort in cohorts:
        (roots[cohort] / "human").symlink_to(human, target_is_directory=True)
        monkeypatch.setattr(production, "ROOT", roots[cohort])
        production.run(queue.engine, runtime.PARTITION, models, None)

    baseline = tmp_path / "baseline"
    selected = {"taxonomy_version": "0.1.0", "assets": [
        {"asset_id": r["asset_id"], "status": "prep_failed"} for r in cohorts["old"]]}
    quality = region_quality.load(code)
    baseline_manifest = snapshot.execute(queue.engine, selected, baseline / "snapshot",
                                         quality=quality, code_version="synthetic-baseline")
    settings = load_settings(code / "configs/stats.yaml", code / "configs/collection_targets.yaml",
                             code / "taxonomy")
    settings["strata"] = [r for r in settings["strata"]
                          if r["attributes"]["domain"] == "real_terrain"]
    data = aggregate.aggregate(baseline / "snapshot", baseline_manifest["snapshot_id"], settings)
    production.save(baseline / "selection.json", selected)
    production.save(baseline / "report/report.json",
                    report(baseline / "snapshot", baseline_manifest["snapshot_id"], data, settings))
    production.save(baseline / "aggregate/registration.json", {"supported": 0, "condition4": {}})
    monkeypatch.setattr(statistics, "ROOT", roots["old"])
    monkeypatch.setattr(statistics, "OLD", baseline)
    monkeypatch.setattr(statistics, "OLD_SNAPSHOT", baseline_manifest["snapshot_id"])
    old_output = tmp_path / "old-stats"
    monkeypatch.setattr(statistics, "OUTPUT", old_output)
    monkeypatch.setattr(statistics, "POLICY", "synthetic-v2")
    statistics.main(policy="synthetic-v2")
    old_result = production.read(old_output / "summary.json")
    verified = snapshot.verify(old_output / "snapshot", old_result["snapshot_id"])
    assert verified["counts"]["assets"] == 7607

    old_only, combined = tmp_path / "old-only", tmp_path / "combined"
    common = ["--root", str(roots["new"]), "--baseline", str(old_output),
              "--baseline-snapshot", old_result["snapshot_id"], "--policy", "synthetic-v2"]
    monkeypatch.setattr(terrain_statistics, "CODE", code)
    for name in ("ROOT", "OLD", "OLD_SNAPSHOT"):
        monkeypatch.setattr(terrain_statistics, name, getattr(terrain_statistics, name))
    monkeypatch.setattr(sys, "argv", ["terrain_statistics", *common, "--old-only",
                                     "--output", str(old_only)])
    terrain_statistics.main()
    monkeypatch.setattr(sys, "argv", ["terrain_statistics", *common, "--output", str(combined),
                                     "--old-only-output", str(old_only)])
    terrain_statistics.main()
    result = production.read(combined / "comparison.json")
    assert result["new"]["counts"]["assets"] == 10207
    assert production.read(old_only / "comparison.json")["execution"]["diagnostic_old_only"] is True
    invalid = tmp_path / "invalid-comparison"
    monkeypatch.setattr(sys, "argv", ["terrain_statistics", *common, "--output", str(invalid),
                                     "--old-only-output", str(combined)])
    with pytest.raises(ValueError, match="旧のみ"):
        terrain_statistics.main()
    assert not invalid.exists()
    disguised = tmp_path / "disguised-combined"
    shutil.copytree(combined, disguised)
    forged = production.read(disguised / "comparison.json")
    forged["execution"]["diagnostic_old_only"] = True
    forged["execution"]["states"] = {
        k: v for k, v in forged["execution"]["states"].items() if k.startswith("old/")}
    production.save(disguised / "comparison.json", forged)
    monkeypatch.setattr(sys, "argv", ["terrain_statistics", *common, "--output", str(invalid),
                                     "--old-only-output", str(disguised)])
    with pytest.raises(ValueError, match="旧のみ"):
        terrain_statistics.main()
    shutil.copyfile(old_only / "selection.json", disguised / "selection.json")
    with pytest.raises(ValueError, match="snapshotとselection"):
        terrain_statistics.main()
    assert not invalid.exists()
    assert all(path.read_bytes() == raw for path, raw in frozen_files.items())
