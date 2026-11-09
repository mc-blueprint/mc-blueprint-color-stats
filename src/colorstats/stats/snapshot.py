"""ライブDBから切り離した、D15ゲート済みParquetスナップショット。"""

import hashlib
import json
import tempfile
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

import duckdb
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from colorstats.retention import check_selection
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
from colorstats.stats.subject_attributes import COLUMNS as ATTRIBUTE_COLUMNS
from colorstats.stats.subject_attributes import METHOD as ATTRIBUTE_METHOD
from colorstats.stats.supplement import METHOD as SUPPLEMENT_METHOD

TABLES = {
    "assets": "id VARCHAR, sha256 VARCHAR, domain VARCHAR, subject_id VARCHAR, "
              "representative_id VARCHAR, eligible BOOLEAN, reasons JSON, data JSON, "
              "rights_eligible BOOLEAN, analysis_available BOOLEAN",
    "provenance": "asset_id VARCHAR, source_id VARCHAR, data JSON",
    "runs": "id VARCHAR, stage VARCHAR, data JSON",
    "groups": "id VARCHAR, asset_id VARCHAR, run_id VARCHAR, role VARCHAR, "
              "eligible BOOLEAN, data JSON, quality_eligible BOOLEAN, reasons JSON",
    "regions": "id VARCHAR, asset_id VARCHAR, run_id VARCHAR, label VARCHAR, data JSON",
    "observations": "id VARCHAR, asset_id VARCHAR, region_id VARCHAR, run_id VARCHAR, "
                    "eligible BOOLEAN, reasons JSON, data JSON, quality_eligible BOOLEAN",
    "relations": "id VARCHAR, asset_id VARCHAR, run_id VARCHAR, "
                 "eligible BOOLEAN, reasons JSON, data JSON, quality_eligible BOOLEAN",
}
ASSET_COLUMNS = (
    "id", "source_id", "subject_id", "sha256", "domain", "license_class",
    "taxonomy_version", "scene_attributes", "quality", "collected_title", "collected_location",
    "search_provider", "search_query", "search_parameters", "result_rank", "result_page",
    "url", "retrieved_at",
)
RUN_COLUMNS = (
    "id", "stage", "model_name", "weights_hash", "license_class", "config_hash",
    "parameters", "code_version", "taxonomy_version", "started_at", "finished_at", "failure_reason",
    "output_paths",
)
REGION_COLUMNS = (
    "id", "asset_id", "processing_run_id", "taxonomy_version", "label", "instance_id", "bbox",
    "normalized_height", "orientation", "terrain_attributes", "label_source", "confidence",
    "area_ratio",
)
OBSERVATION_COLUMNS = (
    "observed_oklab", "material_oklab", "material_confidence", "area_ratio",
)


def canonical(value):
    """UUID・時刻を文字列化した決定的JSON（NaNは禁止）。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      default=str, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _record(row, names):
    return {name: row[name] for name in names}


def _spool(path, rows):
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(canonical(row) + "\n")


def _load(db, table, path):
    columns = {row[0]: row[1] for row in db.execute(f"DESCRIBE {table}").fetchall()}
    db.read_json(str(path), columns=columns, format="newline_delimited").insert_into(table)


def _read(connection, selection, directory):
    selected = selection["assets"]
    ids = [uuid.UUID(item["asset_id"]) for item in selected]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("空または重複したasset選択です")
    assets = list(connection.execute(
        select(*(getattr(Asset, name) for name in ASSET_COLUMNS))
        .where(Asset.id.in_(ids)).order_by(Asset.id)
    ).mappings())
    if len(assets) != len(ids):
        raise ValueError("選択assetが見つかりません")
    roots = {uuid.UUID(item[key]) for item in selected
             for key in ("prep_run_id", "segment_run_id", "color_run_id") if item.get(key)}
    roots.update(uuid.UUID(reference) for asset in assets
                 for key in ("subject_inference", "scene_inference")
                 if (reference := asset["quality"].get(key, {}).get("run_id")))
    roots.update(uuid.UUID(rid) for rid in selection.get("subject_attribute_run_ids", []))
    closure = select(ProcessingRun.id).where(ProcessingRun.id.in_(roots)).cte(
        "input_runs", recursive=True,
    )
    closure = closure.union(select(ProcessingRunInput.input_run_id).join(
        closure, ProcessingRunInput.run_id == closure.c.id,
    ))
    run_ids = select(closure.c.id)
    runs = list(connection.execute(select(
        *(getattr(ProcessingRun, name) for name in RUN_COLUMNS)
    ).where(ProcessingRun.id.in_(run_ids))).mappings())
    links = list(connection.execute(select(ProcessingRunInput).where(
        ProcessingRunInput.run_id.in_(run_ids),
    )).mappings())
    jobs = list(connection.execute(select(
        Job.run_id, Job.asset_id, Job.stage, Job.status,
    ).where(Job.run_id.in_(run_ids))).mappings())
    sources = list(connection.execute(select(Source).where(
        Source.id.in_({asset["source_id"] for asset in assets}),
    )).mappings())
    subjects = list(connection.execute(select(Subject).where(
        Subject.id.in_({asset["subject_id"] for asset in assets if asset["subject_id"]}),
    )).mappings())
    candidates = list(connection.execute(select(SubjectCandidate).where(
        SubjectCandidate.asset_id.in_(ids),
    ).order_by(SubjectCandidate.asset_id, SubjectCandidate.subject_id)).mappings())
    segment_ids = [uuid.UUID(item["segment_run_id"]) for item in selected
                   if item.get("segment_run_id")]
    color_ids = [uuid.UUID(item["color_run_id"]) for item in selected if item.get("color_run_id")]
    regions = list(connection.execute(select(Region).where(
        Region.processing_run_id.in_(segment_ids),
    ).order_by(Region.id)).mappings())
    # 大きな観測・関係はメモリへ全件を溜めず、固定取引から一度だけ退避する。
    result = connection.execution_options(stream_results=True, yield_per=4096).execute(
        select(ColorObservation).where(ColorObservation.processing_run_id.in_(color_ids))
    )
    _spool(directory / "raw_observations.jsonl", (
        {"id": row["id"], "asset_id": row["asset_id"], "region_id": row["region_id"],
         "run_id": row["processing_run_id"], "data": _record(row, OBSERVATION_COLUMNS)}
        for row in result.mappings()
    ))
    result = connection.execute(select(Relation).where(Relation.processing_run_id.in_(color_ids)))
    _spool(directory / "raw_relations.jsonl", (
        {"id": row["id"], "asset_id": row["asset_id"], "region_a": row["region_a"],
         "region_b": row["region_b"], "run_id": row["processing_run_id"], "data": dict(row)}
        for row in result.mappings()
    ))
    return {
        "assets": assets, "runs": runs, "links": links, "jobs": jobs, "sources": sources,
        "subjects": subjects, "candidates": candidates, "regions": regions,
    }


def _inputs(run_id, asset_id, taxonomy, records, jobs, seen, active):
    if run_id in active:
        raise ValueError("入力runの参照が循環しています")
    if run_id in seen:
        return
    active.add(run_id)
    row = records.get(run_id)
    if row is None:
        raise ValueError("入力runが見つかりません")
    if (row["finished_at"] is None or row["failure_reason"] is not None
            or row["taxonomy_version"] != taxonomy):
        raise ValueError("入力runが成功済みの同じtaxonomyではありません")
    if row["stage"] in {"prep", "segment", "shade", "color"}:
        job = jobs.get(run_id)
        if (job is None or job["asset_id"] != asset_id or job["status"] != "succeeded"
                or job["stage"] != row["stage"]):
            raise ValueError("入力runのassetまたは成功jobが一致しません")
    elif row["stage"] == "review":
        job = jobs.get(run_id)
        if (job is None or job["asset_id"] != asset_id or job["status"] != "succeeded"
                or row["parameters"].get("kind") not in {"privacy_review", "image_gate"}):
            raise ValueError("画像reviewの由来が一致しません")
    elif row["stage"] != "subject":
        raise ValueError("対応しない解析stageです")
    for parent in row["input_run_ids"]:
        _inputs(parent, asset_id, taxonomy, records, jobs, seen, active)
    active.remove(run_id)
    seen[run_id] = row



def _subject_attributes(selection, runs, subjects):
    evidence = {}
    for reference in selection.get("subject_attribute_run_ids", []):
        rid = uuid.UUID(reference)
        run = runs.get(rid)
        if (run is None or run["stage"] != "subject"
                or run["parameters"].get("method") != ATTRIBUTE_METHOD):
            raise ValueError("属性根拠にはsubject属性runを指定してください")
        raw = Path(run["output_paths"]["snapshot"]).read_bytes()
        saved = json.loads(raw)
        if (saved["run_id"] != str(rid) or saved["dry_run"]
                or saved["config_hash"] != run["config_hash"]
                or {k: v for k, v in saved.items() if k != "subjects"} != run["parameters"]):
            raise ValueError("属性根拠snapshotが成功runと一致しません")
        for row in saved["subjects"]:
            sid = uuid.UUID(row["subject_id"])
            if sid not in subjects:
                continue
            if sid in evidence:
                raise ValueError("同じsubjectの属性根拠runが重複しています")
            for key, column in ATTRIBUTE_COLUMNS.items():
                value = subjects[sid][column]
                if (row["after"][key] != value or row["attributes"][key]["value"] != value
                        or row["attributes"][key]["state"] not in {
                            "inferred", "unknown", "preserved",
                        }):
                    raise ValueError("属性根拠snapshotと固定subject値が一致しません")
            evidence[sid] = dict(row) | {
                "run_id": str(rid), "method": ATTRIBUTE_METHOD,
                "config_hash": run["config_hash"],
                "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
            }
    return evidence

def _collect(db, selection, quality, records, directory):
    counts, reasons = Counter(), Counter()
    by_id = {uuid.UUID(item["asset_id"]): item for item in selection["assets"]}
    sources = {row["id"]: row for row in records["sources"]}
    subjects = {row["id"]: row for row in records["subjects"]}
    jobs = {row["run_id"]: row for row in records["jobs"]}
    parents = defaultdict(list)
    for link in records["links"]:
        parents[link["run_id"]].append(link["input_run_id"])
    runs = {row["id"]: dict(row) | {
        "input_run_ids": sorted(parents[row["id"]], key=str),
    } for row in records["runs"]}
    attributes = _subject_attributes(selection, runs, subjects)
    candidates, regions = defaultdict(list), defaultdict(list)
    for row in records["candidates"]:
        candidates[row["asset_id"]].append(dict(row))
    for row in records["regions"]:
        regions[row["processing_run_id"]].append(row)
    rows = {table: [] for table in TABLES if table not in {"observations", "relations"}}
    colors, tasks, written_runs = [], [], {}
    taxonomy = selection["taxonomy_version"]
    for asset in records["assets"]:
        aid, item = asset["id"], by_id[asset["id"]]
        if item.get("contract") == "image-review-v1":
            asset = dict(asset) | {"domain": item["analysis_domain"]}
        source = sources[asset["source_id"]]
        adopted, chosen = {}, {}
        for stage in ("prep", "segment", "color"):
            if value := item.get(stage + "_run_id"):
                rid = uuid.UUID(value)
                _inputs(rid, aid, taxonomy, runs, jobs, adopted, set())
                if runs[rid]["stage"] != stage:
                    raise ValueError("選択runのstageが一致しません")
                chosen[stage] = rid
        if asset["taxonomy_version"] != taxonomy:
            raise ValueError("assetのtaxonomyが一致しません")
        if len(chosen) == 3:
            for child, parent in (("segment", "prep"), ("color", "prep"), ("color", "segment")):
                if chosen[parent] not in runs[chosen[child]]["input_run_ids"]:
                    raise ValueError("選択runの直接入力が一致しません")
            payload = runs[chosen["segment"]]["parameters"].get("payload", {})
            if any(payload.get(k) != v for k, v in quality["segment"].items()):
                raise ValueError("採用分割設定と入力runが一致しません")
        for key in ("subject_inference", "scene_inference"):
            if reference := asset["quality"].get(key, {}).get("run_id"):
                rid = uuid.UUID(reference)
                _inputs(rid, aid, taxonomy, runs, jobs, adopted, set())
                if runs[rid]["stage"] != "subject":
                    raise ValueError("推定根拠runのstageが一致しません")
        quality_license = dict(asset["quality"])
        origin = dict(source)
        metadata = quality_license.get("metadata", {})
        selected = metadata.get("openverse", {})
        name = quality_license.get("license")
        if (asset["search_provider"] == "openverse" and metadata.get("source_verified")
                and name in ("by", "by-sa") and selected.get("license") == name
                and source["license"] == name):
            quality_license["license"] = origin["license"] = (
                f"cc-{name}-{selected.get('license_version')}"
            )
        excluded = exclusion_reasons(
            dict(asset) | {"quality": quality_license}, origin,
            [run for run in adopted.values() if not (
                run["stage"] == "subject" and run["parameters"].get("method") == SUPPLEMENT_METHOD
            )],
        )
        attribute_evidence = attributes.get(asset["subject_id"])
        if attribute_evidence:
            rid = uuid.UUID(attribute_evidence["run_id"])
            _inputs(rid, aid, taxonomy, runs, jobs, adopted, set())
        rights = not excluded
        counts["rights_eligible"] += rights
        if len(chosen) != 3:
            excluded.append("missing_analysis")
        domain_valid = asset["domain"] in {"real_building", "real_terrain"}
        if not domain_valid:
            excluded.append("unsupported_domain")
        available = len(chosen) == 3 and domain_valid
        eligible = not excluded
        subject = dict(subjects[asset["subject_id"]]) if asset["subject_id"] else None
        if subject and subject["domain"] != asset["domain"]:
            raise ValueError("subjectのdomainが一致しません")
        if attribute_evidence:
            subject["attribute_evidence"] = attribute_evidence
        data = dict(asset) | {
            "selection": item, "subject": subject, "candidates": candidates[aid],
            "d15_license": {"asset": quality_license.get("license"), "source": origin["license"]},
        }
        rows["assets"].append({
            "id": aid, "sha256": asset["sha256"], "domain": asset["domain"],
            "subject_id": asset["subject_id"], "representative_id": None,
            "eligible": eligible, "reasons": sorted(excluded), "data": data,
            "rights_eligible": rights, "analysis_available": available,
        })
        rows["provenance"].append({
            "asset_id": aid, "source_id": source["id"], "data": dict(source),
        })
        written_runs.update(adopted)
        selected_regions = regions[chosen["segment"]] if "segment" in chosen else []
        for row in selected_regions:
            if row["asset_id"] != aid:
                raise ValueError("領域のassetが一致しません")
            rows["regions"].append({
                "id": row["id"], "asset_id": aid, "run_id": row["processing_run_id"],
                "label": row["label"], "data": _record(row, REGION_COLUMNS),
            })
        if "color" in chosen:
            colors.append({"id": chosen["color"], "asset_id": aid,
                           "segment_id": chosen.get("segment")})
        expiry = asset["quality"].get("retention_until")
        image_available = not expiry or datetime.fromisoformat(expiry) > datetime.now(UTC)
        if available and image_available:
            tasks.append((asset, chosen, selected_regions, runs[chosen["color"]],
                          runs[chosen["segment"]]))
        counts["assets"] += 1
        counts["analysis_eligible"] += eligible
        reasons.update(excluded)
    rows["runs"] = [{"id": rid, "stage": run["stage"], "data": run}
                    for rid, run in sorted(written_runs.items(), key=lambda item: str(item[0]))]
    for table in ("assets", "provenance", "runs", "regions"):
        path = directory / (table + ".jsonl")
        _spool(path, rows[table])
        _load(db, table, path)
    db.execute("CREATE TEMP TABLE chosen_colors (id VARCHAR, asset_id VARCHAR, segment_id VARCHAR)")
    _spool(directory / "colors.jsonl", colors)
    _load(db, "chosen_colors", directory / "colors.jsonl")
    db.execute("CREATE TEMP TABLE supported (domain VARCHAR, label VARCHAR)")
    _spool(directory / "supported.jsonl", (
        {"domain": domain, "label": label}
        for domain, labels in quality["supported_by_domain"].items() for label in labels
    ))
    _load(db, "supported", directory / "supported.jsonl")
    _observations(db, directory)
    # 画像・マスクは固定DB値との照合後、取引外で一度ずつ読む。
    _spool(directory / "groups.jsonl", (
        row for task in tasks for row in _groups(*task, quality)
    ))
    _load(db, "groups", directory / "groups.jsonl")
    db.execute("""
        UPDATE assets SET representative_id = representatives.id
        FROM (SELECT sha256, min(id) AS id FROM assets WHERE eligible GROUP BY sha256)
        AS representatives WHERE assets.sha256 = representatives.sha256
    """)
    duplicates = db.execute("""
        SELECT count(*) FROM assets WHERE eligible AND id <> representative_id
    """).fetchone()[0]
    db.execute("""
        UPDATE assets SET eligible = false, reasons = '["sha_duplicate"]'
        WHERE eligible AND id <> representative_id
    """)
    reasons["sha_duplicate"] = duplicates
    for table in ("observations", "relations", "groups"):
        db.execute(f"""
            UPDATE {table} SET eligible = quality_eligible AND assets.eligible,
                reasons = to_json(list_sort(list_distinct(list_concat(
                    {table}.reasons::VARCHAR[], assets.reasons::VARCHAR[]))))
            FROM assets WHERE {table}.asset_id = assets.id
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


def _observations(db, directory):
    db.execute("""
        CREATE TEMP TABLE raw_observations (
            id VARCHAR, asset_id VARCHAR, region_id VARCHAR, run_id VARCHAR, data JSON)
    """)
    _load(db, "raw_observations", directory / "raw_observations.jsonl")
    invalid = db.execute("""
        SELECT count(*) FROM raw_observations o
        LEFT JOIN chosen_colors c ON o.run_id = c.id
        LEFT JOIN regions r ON o.region_id = r.id
        WHERE c.id IS NULL
           OR (o.region_id IS NULL AND o.asset_id IS DISTINCT FROM c.asset_id)
           OR (o.region_id IS NOT NULL AND
               (r.id IS NULL OR r.asset_id <> c.asset_id OR r.run_id <> c.segment_id))
    """).fetchone()[0]
    if invalid:
        raise ValueError("観測のasset・領域が選択runと一致しません")
    db.execute("""
        INSERT INTO observations
        SELECT o.id, c.asset_id, o.region_id, o.run_id, false,
            CASE WHEN o.region_id IS NULL THEN '["whole_image"]'
                 WHEN s.label IS NULL THEN '["unvalidated_label"]' ELSE '[]' END::JSON,
            o.data, o.region_id IS NOT NULL AND s.label IS NOT NULL
        FROM raw_observations o JOIN chosen_colors c ON o.run_id = c.id
        JOIN assets a ON a.id = c.asset_id
        LEFT JOIN regions r ON r.id = o.region_id
        LEFT JOIN supported s ON s.domain = a.domain AND s.label = r.label
    """)
    db.execute("""
        CREATE TEMP TABLE raw_relations (
            id VARCHAR, asset_id VARCHAR, region_a VARCHAR, region_b VARCHAR,
            run_id VARCHAR, data JSON)
    """)
    _load(db, "raw_relations", directory / "raw_relations.jsonl")
    invalid = db.execute("""
        SELECT count(*) FROM raw_relations o
        LEFT JOIN chosen_colors c ON o.run_id = c.id
        LEFT JOIN regions a ON a.id = o.region_a
        LEFT JOIN regions b ON b.id = o.region_b
        WHERE c.id IS NULL OR o.asset_id <> c.asset_id OR a.id IS NULL OR b.id IS NULL
           OR a.asset_id <> c.asset_id OR b.asset_id <> c.asset_id
           OR a.run_id <> c.segment_id OR b.run_id <> c.segment_id
    """).fetchone()[0]
    if invalid:
        raise ValueError("関係の領域が選択分割runと一致しません")
    db.execute("""
        INSERT INTO relations
        SELECT o.id, c.asset_id, o.run_id, false,
            CASE WHEN sa.label IS NULL OR sb.label IS NULL
                 THEN '["unvalidated_label"]' ELSE '[]' END::JSON, o.data,
            sa.label IS NOT NULL AND sb.label IS NOT NULL
        FROM raw_relations o JOIN chosen_colors c ON o.run_id = c.id
        JOIN assets asset ON asset.id = c.asset_id
        JOIN regions a ON a.id = o.region_a JOIN regions b ON b.id = o.region_b
        LEFT JOIN supported sa ON sa.domain = asset.domain AND sa.label = a.label
        LEFT JOIN supported sb ON sb.domain = asset.domain AND sb.label = b.label
    """)


def _groups(asset, chosen, regions, run, segment, quality):
    from types import SimpleNamespace

    import cv2
    import numpy as np
    from PIL import Image

    from colorstats.analyze import color
    from colorstats.analyze.region_policy import reference
    from colorstats.stats.region_quality import approved_roles

    policy = reference(SimpleNamespace(**segment))
    payload = run["parameters"].get("payload", {})
    if policy is not None or payload.get("region_policy") is not None:
        if policy != payload.get("region_policy") or policy is None:
            raise ValueError("snapshotのregion-policyが選択segmentと一致しません")
        if (str(chosen["segment"]) != policy["run_id"]
                or color.config_hash(payload) != run["config_hash"]):
            raise ValueError("snapshotの新policy色入力hashが一致しません")
        supported = approved_roles(quality, segment["parameters"])
        for role, data in color.role_observations(payload).items():
            if not role.startswith(asset["domain"] + "/"):
                continue
            usable = role in supported and not data["missing"]
            reason = ("effective_role_color_missing" if role in supported
                      else "region_policy_quality_unvalidated")
            yield {
                "id": str(uuid.uuid5(chosen["color"], role)), "asset_id": asset["id"],
                "run_id": chosen["color"], "role": role, "eligible": False,
                "data": {**data, "region_policy": policy,
                         "input_config_hash": run["config_hash"]},
                "quality_eligible": usable, "reasons": [] if usable else [reason],
            }
        return

    groups = {role: members for role, members in quality.get("group_members", {}).items()
              if role.startswith(asset["domain"] + "/")
              and set(members) & {row["label"] for row in regions}}
    if not groups:
        return
    payload = run["parameters"]["payload"]
    size = [segment["parameters"]["metrics"][key] for key in ("width", "height")]
    expected = []
    for row in regions:
        if (row["label_source"] != "model" or row["taxonomy_version"] != asset["taxonomy_version"]
                or row["mask_path"] is None
                or row["mask_path"] not in segment["output_paths"].values()):
            raise ValueError("領域の由来・taxonomy・mask_pathが不正です")
        expected.append({
            "region_id": str(row["id"]), "mask_path": row["mask_path"],
            "label_source": "model", "size": size,
        })
    if (payload["regions"] != expected or color.config_hash(payload) != run["config_hash"]):
        raise ValueError("和集合入力の画像・マスク・由来hashが一致しません")
    labels = {str(row["id"]): row["label"] for row in regions}
    threads = cv2.getNumThreads()
    cv2.setNumThreads(1)
    try:
        with Image.open(payload["input_path"]) as image:
            people = None
            if payload.get("person_mask"):
                with Image.open(payload["person_mask"]) as person:
                    people = np.asarray(person.convert("L")) != 0
            masks = {row["region_id"]: color._region_mask(row, image.size) for row in expected
                     if any(labels[row["region_id"]] in members for members in groups.values())}
            for role, members in sorted(groups.items()):
                ids = [row["region_id"] for row in expected
                       if labels[row["region_id"]] in members]
                mask = np.logical_or.reduce([masks[rid] for rid in ids])
                if people is not None:
                    mask &= ~people
                if people is not None and not mask.any():
                    continue
                data = {
                    "members": members, "region_ids": ids,
                    "area_ratio": float(mask.mean()),
                    "observations": color.extract_colors(image, mask),
                    "input_config_hash": run["config_hash"],
                    "color_code_version": color.CODE_VERSION,
                }
                yield {
                    "id": str(uuid.uuid5(chosen["color"], role)), "asset_id": asset["id"],
                    "run_id": chosen["color"], "role": role, "eligible": False,
                    "data": data, "quality_eligible": True, "reasons": [],
                }
    finally:
        cv2.setNumThreads(threads)


def execute(engine, selection, output, *, quality, code_version, dry_run=False):
    """明示run集合を一貫読取りし、取引を閉じてからParquetを生成する。

    outputは未使用ディレクトリ。成功manifestを最後に作り、失敗した出力は再利用しない。
    dry_runでは一時領域だけを使い永続artifactを作らない。DBへの書込みは行わない。
    selectionのsubject_attribute_run_idsで#85の成功属性runを明示選択する。
    qualityはload_qualityで評価artifactを照合した設定、code_versionは固定コード版。
    入力不一致はValueError、DB/I/O例外は呼出し側へ返す。
    戻り値は固定値だけのmanifest。取引識別子と計測値は検証用execution.jsonへ分離し、
    同じ選択・設定・コード版・固定データから同じsnapshot_idを得る。
    """
    selection = json.loads(canonical(selection))
    selection["assets"].sort(key=lambda item: item["asset_id"])
    if "subject_attribute_run_ids" in selection:
        selection["subject_attribute_run_ids"].sort()
    quality = json.loads(canonical(quality))
    if not dry_run and output is None:
        raise ValueError("出力先が必要です")
    with tempfile.TemporaryDirectory(prefix="colorstats-74-") as temporary:
        directory = Path(temporary)
        root = directory if dry_run else Path(output)
        if not dry_run:
            root.mkdir(mode=0o700, parents=True, exist_ok=False)
        started = monotonic()
        with engine.connect() as connection:
            connection.execution_options(isolation_level="REPEATABLE READ")
            with connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                transaction = connection.execute(text(
                    "SELECT txid_current_snapshot()::text AS snapshot, "
                    "current_setting('transaction_isolation') AS isolation, "
                    "current_setting('transaction_read_only') AS read_only"
                )).mappings().one()
                records = _read(connection, selection, directory)
        with Session(engine) as session:
            check_selection(session, selection)
            from colorstats import privacy_review

            run_records = {run["id"]: run for run in records["runs"]}
            for item in selection["assets"]:
                color_id = item.get("color_run_id")
                color_run = run_records.get(uuid.UUID(color_id)) if color_id else None
                payload = color_run["parameters"].get("payload", {}) if color_run else {}
                if privacy_review.is_new(item) or privacy_review.is_new(payload):
                    privacy_review.check_selection(session, item["asset_id"], item)
                    privacy_review.check_selection(session, item["asset_id"], payload)
                    if any(item.get(k) != payload.get(k) for k in privacy_review.FIELDS):
                        raise PermissionError("選択と色解析の人物承認が一致しません")
        read_seconds = monotonic() - started
        with duckdb.connect(str(directory / "work.duckdb"), config={"threads": 1}) as db:
            db.execute("BEGIN")
            for table, schema in TABLES.items():
                db.execute(f"CREATE TABLE {table} ({schema})")
            counts, reasons = _collect(db, selection, quality, records, directory)
            db.execute("COMMIT")
            manifest = {
                "format_version": 2, "gate_version": "D15-v2", "access_scope": "internal",
                "code_version": code_version,
                "taxonomy_version": selection["taxonomy_version"], "selection": selection,
                "selection_hash": digest(selection), "quality": quality,
                "config_hash": digest(quality), "transaction": {
                    "isolation": transaction["isolation"], "read_only": transaction["read_only"],
                },
                "counts": counts, "exclusions": reasons, "files": {},
                "duckdb_version": duckdb.__version__,
                "input_run_ids": [rid for (rid,) in db.execute(
                    "SELECT id FROM runs ORDER BY id"
                ).fetchall()],
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
            with (root / "execution.json").open("x", encoding="utf-8") as stream:
                stream.write(canonical({
                    "snapshot_id": manifest["snapshot_id"], "transaction": dict(transaction),
                    "read_seconds": read_seconds, "total_seconds": monotonic() - started,
                }) + "\n")
            with (root / "manifest.json").open("x", encoding="utf-8") as stream:
                stream.write(canonical(manifest) + "\n")
            return manifest


def verify(path, expected_hash):
    """DBなしでmanifestと全Parquetを照合する。expected_hashは信頼済み参照を渡す。"""
    root = Path(path)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    value = {k: v for k, v in manifest.items() if k != "snapshot_id"}
    if (manifest["snapshot_id"] != expected_hash or digest(value) != expected_hash
            or manifest["format_version"] not in (1, 2)):
        raise ValueError("manifestのhashまたは形式が一致しません")
    if set(manifest["files"]) != {table + ".parquet" for table in TABLES}:
        raise ValueError("Parquet一覧が一致しません")
    _verify_files(root, manifest)
    return manifest


def _verify_files(root, manifest):
    with duckdb.connect(config={"threads": 1}) as db:
        for name, record in manifest["files"].items():
            with (root / name).open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != record["sha256"]:
                raise ValueError("Parquetのhashが一致しません")
            rows = db.execute(
                "SELECT count(*) FROM read_parquet(?)", [str(root / name)]
            ).fetchone()[0]
            if rows != record["rows"]:
                raise ValueError("Parquetの件数が一致しません")
