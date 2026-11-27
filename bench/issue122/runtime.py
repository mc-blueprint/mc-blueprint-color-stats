"""単独GPUでの再開に共通する接続・不変参照の検証。判定は既存writerへ委ねる。"""

import hashlib
import json
import os
import socket
from pathlib import Path, PurePosixPath
from uuid import UUID

HOST = "ubuntu-1"
PARTITION = "ubuntu1"
VERSION = "production-restart-v2"
HISTORICAL = ("/mnt/data/derived/issue122-20261109",
              "/mnt/data/derived/issue114-terrain-20261110")


def new_root(path):
    """明示された絶対パスだけを新しい実行先とし、旧成果の配下を拒否する。"""
    path = Path(path)
    if not path.is_absolute() or any(path.resolve().is_relative_to(p) for p in HISTORICAL):
        raise ValueError("新規の絶対rootが必要です。旧成果の配下は使用できません")
    return path.resolve()


def remote_root(value):
    """Windows側でもremoteの絶対rootをローカルで解決せず検査する。"""
    path = PurePosixPath(value)
    if (not path.is_absolute() or ".." in path.parts
            or any(path.is_relative_to(p) for p in HISTORICAL)):
        raise ValueError("remoteの新規絶対rootが必要です")
    return str(path)


def prepare_output(root, output, policy):
    """新しい統計出力先を作り、再開時は同じroot・policyの出力だけを使う。"""
    root, output = new_root(root), new_root(output)
    identity = {"root": str(root), "policy": policy, "version": VERSION}
    marker = output / "restart.json"
    if output.exists():
        if not marker.is_file() or json.loads(marker.read_text()) != identity:
            raise FileExistsError("別の統計出力先です。既存成果を上書きしません")
    else:
        output.mkdir(mode=0o700, parents=True)
        with marker.open("x", encoding="utf-8") as stream:
            json.dump(identity, stream, ensure_ascii=False)
        marker.chmod(0o600)


def database():
    """現行hostのlocal peer接続を使う。秘密ファイルやDATABASE_URLは読まない。"""
    import pwd

    import psycopg
    from sqlalchemy import create_engine

    if socket.gethostname() != HOST:
        raise RuntimeError("本番接続はubuntu-1だけで許可されます")

    def connect():
        previous = os.geteuid()
        account = pwd.getpwnam("postgres").pw_uid
        if previous not in {0, account}:
            raise PermissionError("local peer接続を使える実行権限が必要です")
        try:
            os.seteuid(account)
            return psycopg.connect(dbname="colorstats", host="/var/run/postgresql")
        finally:
            os.seteuid(previous)

    return create_engine("postgresql+psycopg://", creator=connect, hide_parameters=True)


def partitions(plan):
    """新計画の単独partitionと、旧成果の読取り用partitionを区別する。"""
    return plan.get("partitions", ["ubuntu1", "ubuntu2"])


def read_plan(root):
    """新rootでは現行manifest・目視条件・固定SHAを必須とする。"""
    raw = (root / "plan.json").read_bytes()
    plan = json.loads(raw)
    if plan.get("version") != VERSION or not plan.get("human_sampling"):
        raise ValueError("現行manifestと目視の固定条件が必要です")
    execution = json.loads((root / "execution.json").read_text())
    if (execution["plan_sha256"] != hashlib.sha256(raw).hexdigest()
            or plan["partitions"] != [PARTITION]):
        raise ValueError("固定manifestまたは単独worker構成が変更されています")
    return plan


def segment_reference(session, row, run_id, settings, models):
    """成功したBの由来・設定・model/policy・全maskを照合して再利用参照を返す。"""
    from sqlalchemy import select

    from colorstats.analyze import region_policy, segment
    from colorstats.schema.models import Job, ProcessingRun

    run = session.get(ProcessingRun, UUID(str(run_id)))
    job = session.scalar(select(Job).where(Job.run_id == run.id)) if run else None
    if (job is None or str(job.asset_id) != row["asset_id"] or job.stage != "segment"
            or job.status != "succeeded" or not run.finished_at or run.failure_reason):
        raise ValueError("再利用Bは同じ対象の成功runである必要があります")
    for key in ("input_path", "input_run_id", "input_sha256"):
        if job.payload.get(key) != row[key]:
            raise ValueError("再利用Bの入力が一致しません")
    payload = run.parameters.get("payload", {})
    if any(job.payload.get(k) != v or payload.get(k) != v for k, v in settings.items()):
        raise ValueError("再利用Bのpayloadにmethod・prompt・閾値の明示が必要です")
    configuration = segment._configuration({**job.payload, "model_paths": {
        name: str(models / name) for name in ("sam2", "dino", "oneformer")}})
    if any(configuration[k] != run.parameters.get(k) for k in configuration if k != "payload"):
        raise ValueError("再利用Bのモデル・前処理が一致しません")
    policy = region_policy.reference(run)
    if policy is None:
        raise ValueError("再利用Bに有効maskがありません")
    region_policy.load_masks({**job.payload, "region_run_id": str(run.id), "region_policy": policy})
    return str(run.id)


def reused_segments(session, source, rows, settings, models):
    """旧recordsは読み取るだけで、検証済みBの参照だけを新計画へ渡す。"""
    plan = json.loads((source / "plan.json").read_text())
    records = {}
    for part in partitions(plan):
        subset = json.loads((source / part / "records.json").read_text())
        if records.keys() & subset.keys():
            raise ValueError("旧recordsに対象の重複があります")
        records.update(subset)
    return {row["asset_id"]: segment_reference(session, row,
            records[row["asset_id"]]["segment_run_id"], settings, models) for row in rows
            if records.get(row["asset_id"], {}).get("segment_run_id")}


def sampling(path):
    """表示前に用意した母集団・seed・合格条件・提示集合を固定する。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    groups = data.get("groups", {})
    sizes = {"terrain_required": 14, "random_old": 50, "random_new": 50, "challenge": 10}
    if (set(groups) != set(sizes) or any(len(set(groups[k])) != n for k, n in sizes.items())
            or set(groups["random_old"]) & set(groups["random_new"])
            or set(groups["challenge"]) & set(groups["random_old"] + groups["random_new"])):
        raise ValueError("地形14・旧新50ずつ・challenge10を重複ルールどおり固定してください")
    if (not data.get("population_sha256") or type(data.get("seed")) is not int
            or data.get("criteria") != {"max_problems": 0}
            or not data.get("required_ids")
            or len(data["required_ids"]) != len(set(data["required_ids"]))):
        raise ValueError("母集団SHA・seed・問題0件の合格条件・重複しない提示集合が必要です")
    if set(data["required_ids"]) != {aid for values in groups.values() for aid in values}:
        raise ValueError("目視の群と提示集合が一致しません")
    return data


def human_reviews(session, root, plan):
    """#120の固定提示と追記済み確認runを照合し、参照だけを返す。DB更新はしない。"""
    from bench.issue114.mobile import nonpresented_reviews, reply_reviews

    from colorstats import privacy_review

    sampling = plan.get("human_sampling")
    if not sampling:
        raise PermissionError("新計画には目視の固定条件が必要です")
    directory = root / "human"
    names = ["number-map.json", "review-manifest.json", "converted-review.json"]
    if not all((directory / name).is_file() for name in names):
        raise PermissionError("新しい目視確認の提示・返信・runが揃っていません")
    raw = [(directory / name).read_bytes() for name in names]
    mapping, manifest, applied = [json.loads(value) for value in raw]
    if manifest.get("sampling") != sampling:
        raise ValueError("目視の母集団・seed・合格条件が固定計画と一致しません")
    if manifest.get("view", "comparison") != "comparison":
        raise PermissionError("統計には比較表示を確認した提示runが必要です")
    held = nonpresented_reviews(session, manifest)
    expected = reply_reviews(mapping, directory / "review-manifest.json",
                             manifest["decisions_sha256"], applied["chat_reply"],
                             directory=directory, db=session.get_bind())
    if hashlib.sha256(raw[1]).hexdigest() != mapping["review_manifest_sha256"]:
        raise ValueError("P6のmanifestがDBに固定した提示と一致しません")
    if any(applied.get(k) != v for k, v in expected.items() if k != "rows"):
        raise ValueError("目視返信と固定番号表が一致しません")
    if len(applied["rows"]) != len(expected["rows"]):
        raise ValueError("目視返信の対象が不足しています")
    references = {}
    for row, original in zip(applied["rows"], expected["rows"], strict=True):
        if any(row.get(k) != v for k, v in original.items()):
            raise ValueError("目視返信の対象・提示参照が一致しません")
        run = privacy_review.review(session, row["asset_id"], row["recorded_privacy_review_run_id"])
        p, evidence = run.parameters, run.parameters["evidence"]
        if (p["method"] != "human" or p["reviewer"] != "ユーザー"
                or p["input_run_id"] != row["privacy_review_run_id"]
                or p["presented_source_sha256"] != row["presented_source_sha256"]
                or p["note"] != row["note"]
                or evidence["image_gate_run_id"] != row["image_gate_run_id"]
                or evidence["region_policy_run_id"] != row["region_policy_run_id"]
                or (row["error_found"] and not evidence["human_hold"])):
            raise ValueError("目視の追記runと提示・返信が一致しません")
        references[row["asset_id"]] = str(run.id)
    if not expected["confirm_no_errors"]:
        raise PermissionError("目視の問題が未解決です。合格条件を緩めて統計へ進めません")
    references.update(held)
    return references
