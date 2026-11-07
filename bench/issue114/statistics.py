"""#105の旧selectionとバッチ1の新規成功runから別版の統計を作り、旧行を照合する。"""

import argparse
import hashlib
import json
from collections import Counter
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from bench.issue75.production import summarize
from bench.issue105.production import engine
from bench.issue114.batch1 import check_analysis
from bench.issue114.privacy import review_state
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from colorstats.queue import Queue
from colorstats.schema.models import Job, ProcessingRun, RuleStat
from colorstats.stats import aggregate as handler
from colorstats.stats.aggregate_cli import load_settings
from colorstats.stats.report import markdown, report
from colorstats.stats.snapshot import canonical, execute
from colorstats.stats.snapshot_cli import load_quality

ROOT = Path(__file__).resolve().parents[2]
OLD = Path("/mnt/data/derived/stats/issue105-corrected-20261105T105836Z")


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(canonical(value) + "\n")


def preserved(db, batch):
    result = {}
    with db.connect() as connection:
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        for name, table in (("assets", "asset"), ("runs", "processing_run")):
            before = json.loads((batch / f"baseline-{name}.json").read_text())
            after = dict(connection.execute(text(
                f"SELECT id::text,md5(row_to_json(t)::text) FROM {table} t ORDER BY id"
            )).all())
            changed = [key for key, value in before.items() if after.get(key) != value]
            result[name] = {"before": len(before), "changed": changed}
            if changed:
                raise ValueError(f"旧{name}が変更されています: {len(changed)}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--code-version", required=True)
    args = parser.parse_args()
    root, batch = args.output, args.batch
    analyses = {}
    for name in ("ubuntu1", "ubuntu2"):
        result = json.loads((batch / name / "report.json").read_text())
        check_analysis(result, len(json.loads((batch / f"{name}-assets.json").read_text())))
        analyses[name] = result
    approval = batch / "privacy-validation.json"
    if not approval.exists():
        raise ValueError("目視サンプルの確認結果が未登録です")
    validation = json.loads(approval.read_text())
    if (not validation["approved"] or validation["decisions_sha256"]
            != hashlib.sha256((batch / "privacy-decisions.json").read_bytes()).hexdigest()):
        raise ValueError("目視サンプルの承認と現在の自動判定が一致しません")
    root.mkdir(parents=True, exist_ok=False)
    db = engine(False)
    try:
        decisions = json.loads((batch / "privacy-decisions.json").read_text())
        if validation["review_state_sha256"] != review_state(
            db, [row["asset_id"] for row in decisions],
        ):
            raise ValueError("目視確認後に人物判定が変更されています")
        save(root / "preserved-before.json", preserved(db, batch))
        selection = json.loads((OLD / "selection.json").read_text())
        identifiers = [UUID(value) for value in json.loads((batch / "new-assets.json").read_text())]
        new_rows = {str(value): {"asset_id": str(value)} for value in identifiers}
        with Session(db) as session:
            for item in json.loads((batch / "prep-report.json").read_text()):
                if item["asset_id"] in new_rows and item["status"] == "succeeded":
                    new_rows[item["asset_id"]]["prep_run_id"] = item["run_id"]
            for result in analyses.values():
                for job in result["jobs"]:
                    if job["stage"] in ("segment", "color") and job["status"] == "succeeded":
                        new_rows[job["asset_id"]][job["stage"] + "_run_id"] = job["run_id"]
            old_ids = {item["asset_id"] for item in selection["assets"]}
            if old_ids & new_rows.keys():
                raise ValueError("旧版と新規cohortが重複しています")
            selection["assets"].extend(new_rows.values())
        save(root / "selection.json", selection)
        manifest = execute(db, selection, root / "snapshot",
                           quality=load_quality(ROOT / "configs/segment_stats.yaml"),
                           code_version=args.code_version)
        settings = load_settings(
            ROOT / "configs/stats.yaml", ROOT / "configs/collection_targets.yaml",
            ROOT / "taxonomy",
        )
        payload = {"snapshot": str(root / "snapshot"), "snapshot_id": manifest["snapshot_id"],
                   "settings": settings, "output_path": str(root / "aggregate/statistics.json")}
        data = handler.aggregate(root / "snapshot", manifest["snapshot_id"], settings)
        save(root / "aggregate/dry.json", data)
        queue = Queue(db, lease=timedelta(minutes=30))
        jid = queue.enqueue("aggregate", None, handler.config_hash(payload), payload)
        claim = queue.claim(["aggregate"], job_ids=[jid])
        if claim is None:
            raise ValueError("新しいaggregate jobを取得できません")
        try:
            prepared = handler.prepare(claim)
            if prepared.data != data:
                raise ValueError("固定計算が一致しません")
            queue.renew(claim)
            rid = queue.complete(claim, prepared.info,
                                 lambda session, run: handler.register(session, run, data),
                                 prepared.files)
        except BaseException as error:
            queue.fail(claim, type(error).__name__)
            raise
        with Session(db) as session:
            registered = session.scalars(select(RuleStat).where(
                RuleStat.processing_run_id == rid
            )).all()
            rows = [{key: getattr(row, key) for key in data["rows"][0]} for row in registered]
            if sorted(map(canonical, rows)) != sorted(map(canonical, data["rows"])):
                raise ValueError("登録済みrule_statが一致しません")
            if (session.get(Job, jid).status != "succeeded"
                    or session.get(ProcessingRun, rid).failure_reason):
                raise ValueError("統計登録が成功していません")
        summary = summarize(data) | {"job_id": str(jid), "run_id": str(rid)}
        save(root / "aggregate/registration.json", summary)
        rendered = report(root / "snapshot", manifest["snapshot_id"], data, settings)
        privacy = json.loads((batch / "privacy-summary.json").read_text())
        rendered["privacy_review"] = privacy
        save(root / "report/report.json", rendered)
        (root / "report/report.md").write_text(markdown(rendered), encoding="utf-8")
        old_manifest = json.loads((OLD / "snapshot/manifest.json").read_text())
        old_summary = json.loads((OLD / "aggregate/registration.json").read_text())
        sources = Counter()
        with db.connect() as connection:
            for source, count in connection.execute(text(
                "SELECT coalesce(a.search_provider,s.site),count(*) FROM asset a "
                "JOIN source s ON s.id=a.source_id GROUP BY 1"
            )):
                sources[source] += count
        comparison = {
            "old_snapshot": old_manifest["snapshot_id"], "new_snapshot": manifest["snapshot_id"],
            "counts": {"old": old_manifest["counts"], "new": manifest["counts"]},
            "supported": {"old": old_summary["supported"], "new": summary["supported"]},
            "condition4": {"old": old_summary["condition4_passed"],
                           "new": summary["condition4_passed"]},
            "roles": {"old": old_summary["condition4"], "new": summary["condition4"]},
            "actual_database_sources": dict(sources),
            "privacy_review": privacy,
            "source_bias": "全件Commons。ソース多様性の改善は未達。Openverseは未配置で未起動。",
            "excluded_baseline_assets_outside_old_selection": (
                len(json.loads((batch / "baseline-assets.json").read_text())) - len(old_ids)
            ),
            "preserved": preserved(db, batch),
        }
        save(root / "comparison.json", comparison)
        with (root / "report/report.md").open("a", encoding="utf-8") as stream:
            stream.write("\n## DB全体のソース内訳と偏り（snapshot対象外の既存19枚を含む）\n\n"
                         + canonical(dict(sources))
                         + "\n\n全件Commons。Openverseは未配置・未起動。"
                         + "ソース多様性の改善は未達。\n")
            stream.write("\n今回の追加分全体に対する人物判定・採用・目視待ちの件数と理由：\n\n"
                         + canonical(privacy) + "\n")
        print(canonical({"snapshot_id": manifest["snapshot_id"], "run_id": str(rid),
                         "counts": manifest["counts"], "supported": summary["supported"],
                         "condition4": summary["condition4_passed"]}), flush=True)
    finally:
        db.dispose()


if __name__ == "__main__":
    main()
