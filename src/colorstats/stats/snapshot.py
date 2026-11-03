"""ライブDBから切り離した、D15ゲート済みParquetスナップショット。"""

import hashlib
import json
import tempfile
import uuid
from collections import Counter
from pathlib import Path

import duckdb
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from colorstats.schema.models import (
    Asset,
    ColorObservation,
    Job,
    ProcessingRun,
    ProcessingRunInput,
    Region,
    Relation,
    Source,
    Subject,
    SubjectCandidate,
)
from colorstats.stats.licenses import exclusion_reasons

TABLES = {
    "assets": "id VARCHAR, sha256 VARCHAR, domain VARCHAR, subject_id VARCHAR, "
              "representative_id VARCHAR, eligible BOOLEAN, reasons JSON, data JSON",
    "provenance": "asset_id VARCHAR, source_id VARCHAR, data JSON",
    "runs": "id VARCHAR, stage VARCHAR, data JSON",
    "groups": "id VARCHAR, asset_id VARCHAR, run_id VARCHAR, role VARCHAR, "
              "eligible BOOLEAN, data JSON",
    "regions": "id VARCHAR, asset_id VARCHAR, run_id VARCHAR, label VARCHAR, data JSON",
    "observations": "id VARCHAR, asset_id VARCHAR, region_id VARCHAR, run_id VARCHAR, "
                    "eligible BOOLEAN, reasons JSON, data JSON",
    "relations": "id VARCHAR, asset_id VARCHAR, run_id VARCHAR, "
                 "eligible BOOLEAN, reasons JSON, data JSON",
}
ASSET_COLUMNS = (
    "id", "source_id", "subject_id", "sha256", "domain", "license_class",
    "taxonomy_version", "scene_attributes", "quality", "collected_title", "collected_location",
    "search_provider", "search_query", "search_parameters", "result_rank", "result_page",
)
RUN_COLUMNS = (
    "id", "stage", "model_name", "weights_hash", "license_class", "config_hash",
    "parameters", "code_version", "taxonomy_version", "started_at", "finished_at", "failure_reason",
)


def canonical(value):
    """UUID・時刻を文字列化した決定的JSON（NaNは禁止）。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      default=str, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _record(row, names):
    return {name: row[name] for name in names}


def _rows(connection, model, condition):
    return connection.execute(
        select(model).where(condition).order_by(*model.__table__.primary_key)
    ).mappings()


def _inputs(connection, run_id, asset_id, taxonomy, seen, active):
    if run_id in active:
        raise ValueError("入力runの参照が循環しています")
    if run_id in seen:
        return
    active.add(run_id)
    row = connection.execute(select(*(getattr(ProcessingRun, name) for name in RUN_COLUMNS)).where(
        ProcessingRun.id == run_id,
    )).mappings().one()
    if (row["finished_at"] is None or row["failure_reason"] is not None
            or row["taxonomy_version"] != taxonomy):
        raise ValueError("入力runが成功済みの同じtaxonomyではありません")
    if row["stage"] in {"prep", "segment", "shade", "color"}:
        job = connection.execute(select(Job.id).where(
            Job.run_id == run_id, Job.asset_id == asset_id, Job.status == "succeeded",
            Job.stage == row["stage"],
        )).first()
        if job is None:
            raise ValueError("入力runのassetまたは成功jobが一致しません")
    elif row["stage"] != "subject":
        raise ValueError("対応しない解析stageです")
    parents = sorted(connection.scalars(select(ProcessingRunInput.input_run_id).where(
        ProcessingRunInput.run_id == run_id,
    )), key=str)
    for parent in parents:
        _inputs(connection, parent, asset_id, taxonomy, seen, active)
    active.remove(run_id)
    seen[run_id] = _record(row, RUN_COLUMNS) | {"input_run_ids": parents}


def _insert(db, table, rows):
    if rows:
        db.executemany(
            f"INSERT INTO {table} VALUES ({','.join('?' for _ in rows[0])})", rows,
        )


def _collect(connection, db, selection, quality):
    counts = Counter()
    reasons = Counter()
    written_runs = set()
    selected = selection["assets"]
    ids = [uuid.UUID(item["asset_id"]) for item in selected]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("空または重複したasset選択です")
    by_id = dict(zip(ids, selected, strict=True))
    taxonomy = selection["taxonomy_version"]
    # 必要列だけをサーバー側カーソルで取り出し、ORMのidentity mapへ全件を溜めない。
    result = connection.execution_options(stream_results=True, yield_per=256).execute(
        select(*(getattr(Asset, name) for name in ASSET_COLUMNS))
        .where(Asset.id.in_(ids)).order_by(Asset.id)
    )
    for batch in result.mappings().partitions(256):
        for asset in batch:
            aid = asset["id"]
            item = by_id[aid]
            source = connection.execute(select(
                Source.id, Source.url, Source.site, Source.author, Source.license,
                Source.license_class, Source.attribution, Source.policy, Source.retrieved_at,
            ).where(Source.id == asset["source_id"])).mappings().one()
            runs = {}
            chosen = {}
            for stage in ("prep", "segment", "color"):
                value = item.get(stage + "_run_id")
                if value:
                    rid = uuid.UUID(value)
                    _inputs(connection, rid, aid, taxonomy, runs, set())
                    if runs[rid]["stage"] != stage:
                        raise ValueError("選択runのstageが一致しません")
                    chosen[stage] = rid
            if asset["taxonomy_version"] != taxonomy:
                raise ValueError("assetのtaxonomyが一致しません")
            if chosen.keys() == {"prep", "segment", "color"}:
                for child, parent in (("segment", "prep"), ("color", "prep"), ("color", "segment")):
                    if chosen[parent] not in runs[chosen[child]]["input_run_ids"]:
                        raise ValueError("選択runの直接入力が一致しません")
                segment = runs[chosen["segment"]]
                payload = segment["parameters"].get("payload", {})
                settings = quality["segment"]
                if any(payload.get(k) != v for k, v in settings.items()):
                    raise ValueError("採用分割設定と入力runが一致しません")
            for key in ("subject_inference", "scene_inference"):
                reference = asset["quality"].get(key, {}).get("run_id")
                if reference:
                    rid = uuid.UUID(reference)
                    _inputs(connection, rid, aid, taxonomy, runs, set())
                    if runs[rid]["stage"] != "subject":
                        raise ValueError("推定根拠runのstageが一致しません")
            excluded = exclusion_reasons(asset, source, runs.values())
            counts["rights_eligible"] += not excluded
            if len(chosen) != 3:
                excluded.append("missing_analysis")
            if asset["domain"] not in {"real_building", "real_terrain"}:
                excluded.append("unsupported_domain")
            eligible = not excluded
            subject = None
            if asset["subject_id"] is not None:
                subject = connection.execute(select(Subject).where(
                    Subject.id == asset["subject_id"],
                )).mappings().one()
                if subject["domain"] != asset["domain"]:
                    raise ValueError("subjectのdomainが一致しません")
                subject = dict(subject)
            candidates = [dict(row) for row in _rows(
                connection, SubjectCandidate, SubjectCandidate.asset_id == aid,
            )]
            data = dict(asset) | {"selection": item, "subject": subject, "candidates": candidates}
            _insert(db, "assets", [(
                str(aid), asset["sha256"], asset["domain"],
                str(asset["subject_id"]) if subject else None, None, eligible,
                canonical(sorted(excluded)), canonical(data),
            )])
            _insert(db, "provenance", [(str(aid), str(source["id"]), canonical(dict(source)))])
            for rid, run in sorted(runs.items(), key=lambda item: str(item[0])):
                if rid not in written_runs:
                    _insert(db, "runs", [(str(rid), run["stage"], canonical(run))])
                    written_runs.add(rid)
            supported = quality["supported_by_domain"].get(asset["domain"], [])
            region_ids = set()
            if "segment" in chosen:
                for row in _rows(connection, Region, Region.processing_run_id == chosen["segment"]):
                    if row["asset_id"] != aid:
                        raise ValueError("領域のassetが一致しません")
                    region_ids.add(row["id"])
                    data = _record(row, (
                        "id", "asset_id", "processing_run_id", "taxonomy_version", "label",
                        "instance_id", "bbox", "normalized_height", "orientation",
                        "terrain_attributes", "label_source", "confidence", "area_ratio",
                    ))
                    _insert(db, "regions", [(
                        str(row["id"]), str(aid), str(chosen["segment"]), row["label"],
                        canonical(data),
                    )])
            if "color" in chosen:
                for row in _rows(
                    connection, ColorObservation,
                    ColorObservation.processing_run_id == chosen["color"],
                ):
                    if row["region_id"] is None:
                        if row["asset_id"] != aid:
                            raise ValueError("全体観測のassetが一致しません")
                        why = ["whole_image"]
                    else:
                        if row["region_id"] not in region_ids:
                            raise ValueError("観測の領域が選択分割runと一致しません")
                        label = db.execute("SELECT label FROM regions WHERE id = ?",
                                           [str(row["region_id"])]).fetchone()[0]
                        why = [] if label in supported else [
                            "unvalidated_label",
                        ]
                    data = _record(row, (
                        "observed_oklab", "material_oklab", "material_confidence", "area_ratio",
                    ))
                    _insert(db, "observations", [(
                        str(row["id"]), str(aid),
                        str(row["region_id"]) if row["region_id"] else None,
                        str(chosen["color"]), eligible and not why, canonical(why), canonical(data),
                    )])
                for row in _rows(
                    connection, Relation, Relation.processing_run_id == chosen["color"],
                ):
                    if (row["asset_id"] != aid or row["region_a"] not in region_ids
                            or row["region_b"] not in region_ids):
                        raise ValueError("関係の領域が選択分割runと一致しません")
                    labels = [r[0] for r in db.execute(
                        "SELECT label FROM regions WHERE id IN (?, ?)",
                        [str(row["region_a"]), str(row["region_b"])],
                    ).fetchall()]
                    why = [] if all(
                        label in supported for label in labels
                    ) else ["unvalidated_label"]
                    _insert(db, "relations", [(
                        str(row["id"]), str(aid), str(chosen["color"]), eligible and not why,
                        canonical(why), canonical(dict(row)),
                    )])
            if eligible and len(chosen) == 3:
                _groups(connection, db, asset, chosen, runs, quality)
            counts["assets"] += 1
            counts["analysis_eligible"] += eligible
            reasons.update(excluded)
    if counts["assets"] != len(ids):
        raise ValueError("選択assetが見つかりません")
    # 適格な出典間だけで代表を決める。除外された出典の制約は消さない。
    db.execute("""
        UPDATE assets SET representative_id = representatives.id
        FROM (SELECT sha256, min(id) AS id FROM assets WHERE eligible GROUP BY sha256)
        AS representatives WHERE assets.sha256 = representatives.sha256
    """)
    db.execute("""
        UPDATE assets SET eligible = false
        WHERE eligible AND id <> representative_id
    """)
    duplicates = db.execute("""
        SELECT id FROM assets WHERE id <> representative_id AND reasons = '[]'
    """).fetchall()
    for (aid,) in duplicates:
        db.execute("UPDATE assets SET reasons = ? WHERE id = ?", ['["sha_duplicate"]', aid])
    reasons["sha_duplicate"] = len(duplicates)
    for table in ("observations", "relations", "groups"):
        db.execute(f"""
            UPDATE {table} SET eligible = false FROM assets
            WHERE {table}.asset_id = assets.id AND NOT assets.eligible
        """)
    counts["sha_distinct"] = db.execute("SELECT count(DISTINCT sha256) FROM assets").fetchone()[0]
    counts["representatives"] = db.execute(
        "SELECT count(*) FROM assets WHERE eligible"
    ).fetchone()[0]
    counts["confirmed_subjects"] = db.execute(
        "SELECT count(DISTINCT subject_id) FROM assets WHERE eligible"
    ).fetchone()[0]
    for table in TABLES:
        counts[table + "_rows"] = db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    for table in ("observations", "relations", "groups"):
        counts[table + "_eligible"] = db.execute(
            f"SELECT count(*) FROM {table} WHERE eligible"
        ).fetchone()[0]
    return dict(counts), dict(sorted(reasons.items()))


def _groups(connection, db, asset, chosen, runs, quality):
    import numpy as np
    from PIL import Image

    from colorstats.analyze import color

    groups = {role: members for role, members in quality.get("group_members", {}).items()
              if role.startswith(asset["domain"] + "/")}
    labels = dict(db.execute(
        "SELECT id, label FROM regions WHERE asset_id = ?", [str(asset["id"])],
    ).fetchall())
    groups = {role: members for role, members in groups.items()
              if set(members) & set(labels.values())}
    if not groups:
        return
    run = runs[chosen["color"]]
    payload = run["parameters"]["payload"]
    with Session(bind=connection) as session:
        expected = color.region_inputs(session, asset["id"], chosen["segment"])
    if (payload["regions"] != expected or color.config_hash(payload) != run["config_hash"]):
        raise ValueError("和集合入力の画像・マスク・由来hashが一致しません")
    with Image.open(payload["input_path"]) as image:
        for role, members in sorted(groups.items()):
            mask = np.zeros((image.height, image.width), dtype=bool)
            ids = []
            for region in expected:
                if labels[region["region_id"]] in members:
                    mask |= color._region_mask(region, image.size)
                    ids.append(region["region_id"])
            data = {
                "members": members, "region_ids": ids,
                "area_ratio": float(mask.mean()), "observations": color.extract_colors(image, mask),
                "input_config_hash": run["config_hash"], "color_code_version": color.CODE_VERSION,
            }
            rid = str(uuid.uuid5(chosen["color"], role))
            _insert(db, "groups", [(
                rid, str(asset["id"]), str(chosen["color"]), role, True, canonical(data),
            )])


def execute(engine, selection, output, *, quality, code_version, dry_run=False):
    """明示asset/run集合を1つのREAD ONLY/REPEATABLE READ取引で固定する。

    outputは未使用ディレクトリ。成功manifestを最後に作り、失敗した出力は再利用しない。
    dry_runでは一時領域だけを使い永続artifactを作らない。DBへの書込みは行わない。
    qualityはload_qualityで評価artifactを照合した設定、code_versionは固定コード版。
    入力参照・成功状態・taxonomy・設定の不一致はValueError、DB/I/O例外は呼出し側へ返す。
    """
    selection = json.loads(canonical(selection))
    quality = json.loads(canonical(quality))
    if not dry_run and output is None:
        raise ValueError("出力先が必要です")
    with tempfile.TemporaryDirectory(prefix="colorstats-74-") as temporary:
        root = Path(temporary) if dry_run else Path(output)
        if not dry_run:
            root.mkdir(parents=True, exist_ok=False)
        with duckdb.connect(str(Path(temporary) / "work.duckdb")) as db:
            for table, schema in TABLES.items():
                db.execute(f"CREATE TABLE {table} ({schema})")
            with engine.connect() as connection:
                connection.execution_options(isolation_level="REPEATABLE READ")
                with connection.begin():
                    connection.execute(text("SET TRANSACTION READ ONLY"))
                    transaction = connection.execute(text(
                        "SELECT txid_current_snapshot()::text AS snapshot, "
                        "current_setting('transaction_isolation') AS isolation, "
                        "current_setting('transaction_read_only') AS read_only"
                    )).mappings().one()
                    counts, reasons = _collect(connection, db, selection, quality)
            manifest = {
                "format_version": 1, "gate_version": "D15-v1", "code_version": code_version,
                "taxonomy_version": selection["taxonomy_version"], "selection": selection,
                "selection_hash": digest(selection), "quality": quality,
                "config_hash": digest(quality), "transaction": dict(transaction),
                "counts": counts, "exclusions": reasons, "files": {},
                "duckdb_version": duckdb.__version__,
            }
            if dry_run:
                return manifest
            for table in TABLES:
                path = root / (table + ".parquet")
                db.execute(f"COPY (SELECT * FROM {table} ORDER BY ALL) TO ? (FORMAT PARQUET)",
                           [str(path)])
                with path.open("rb") as stream:
                    sha = hashlib.file_digest(stream, "sha256").hexdigest()
                manifest["files"][path.name] = {"sha256": sha, "rows": counts[table + "_rows"]}
            manifest["snapshot_id"] = digest(manifest)
            _verify_files(root, manifest)
            with (root / "manifest.json").open("x", encoding="utf-8") as stream:
                stream.write(canonical(manifest) + "\n")
            return manifest


def verify(path, expected_hash):
    """DBなしでmanifestと全Parquetを検証してmanifestを返す。

    expected_hashは信頼済み呼出し元が保存したsnapshot_id。改変・欠損・版不一致は
    ValueErrorまたはI/O例外とし、検証前のファイルを集計に使用しない。
    """
    root = Path(path)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    value = {k: v for k, v in manifest.items() if k != "snapshot_id"}
    if (manifest["snapshot_id"] != expected_hash or digest(value) != expected_hash
            or manifest["format_version"] != 1):
        raise ValueError("manifestのhashまたは形式が一致しません")
    if set(manifest["files"]) != {table + ".parquet" for table in TABLES}:
        raise ValueError("Parquet一覧が一致しません")
    _verify_files(root, manifest)
    return manifest


def _verify_files(root, manifest):
    for name, record in manifest["files"].items():
        with (root / name).open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != record["sha256"]:
            raise ValueError("Parquetのhashが一致しません")
        with duckdb.connect() as db:
            rows = db.execute(
                "SELECT count(*) FROM read_parquet(?)", [str(root / name)]
            ).fetchone()[0]
        if rows != record["rows"]:
            raise ValueError("Parquetの件数が一致しません")
