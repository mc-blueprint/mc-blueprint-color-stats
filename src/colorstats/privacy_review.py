"""画像と画素の人物根拠を別review runへ固定する。実在人物は当面保留する。"""

import hashlib
import json
import uuid
from pathlib import Path

import numpy as np
from PIL import Image
from sqlalchemy import select

from colorstats import image_gate, retention
from colorstats.analyze import region_policy
from colorstats.api_budget import digest
from colorstats.queue import RunInfo
from colorstats.queue.worker import Prepared
from colorstats.schema.models import Asset, Job, ProcessingRun, ProcessingRunInput

POLICY = {"version": "privacy-review-v1", "real_people": "pending",
          "uncertain": "pending", "disagreement": "pending", "mask_rescue": False}
FIELDS = ("image_gate_run_id", "image_gate_hash", "image_gate_input_sha256",
          "analysis_domain", "privacy_review_run_id", "privacy_review_hash",
          "region_policy_run_id", "region_policy_hash", "input_sha256", "size",
          "person_mask_sha256")


def decision(people, pixels):
    """両根拠が陰性のときだけ採用可能とする。像・絵のsemantic陽性も保留する。"""
    if people not in {"present", "absent"} or pixels is None:
        return {"decision": "pending", "reason": "unknown_evidence"}
    if (people == "present") != (pixels > 0):
        return {"decision": "pending", "reason": "disagreement"}
    if people == "present":
        return {"decision": "pending", "reason": "real_people"}
    return {"decision": "accepted", "reason": "both_absent"}


def _run(session, asset_id, run_id, stage, kind=None):
    run = session.get(ProcessingRun, uuid.UUID(str(run_id)))
    job = session.scalar(select(Job).where(
        Job.run_id == run_id, Job.asset_id == asset_id, Job.stage == stage,
        Job.status == "succeeded"))
    if (run is None or run.stage != stage or run.finished_at is None
            or run.failure_reason is not None or job is None
            or (kind and run.parameters.get("kind") != kind)):
        raise PermissionError("同じ画像の成功済みrunが必要です")
    return run


def _not_corrected(session, run):
    child = session.scalar(select(ProcessingRun.id).where(
        ProcessingRun.stage == "review", ProcessingRun.finished_at.is_not(None),
        ProcessingRun.parameters["input_run_id"].astext == str(run.id),
        ProcessingRun.parameters["method"].astext == "human",
        ProcessingRun.parameters["kind"].astext.in_(["privacy_review", "image_gate"])))
    if child:
        raise PermissionError("人の訂正により古い判定・解析承認は失効しています")


def evidence(session, asset_id, gate_id, segment_id):
    """完了済みA/Bと私有artifactを照合し、座標・SHAと独立した二つの根拠を返す。

    API通信や判定更新はしない。不正な参照・改変はPermissionError/ValueError。
    """
    asset_id = uuid.UUID(str(asset_id))
    retention.assert_usable(session, asset_id, images=True)
    asset = session.get(Asset, asset_id)
    gate = _run(session, asset_id, gate_id, "review", "image_gate")
    segment = _run(session, asset_id, segment_id, "segment")
    _not_corrected(session, gate)
    p = gate.parameters
    raw = Path(asset.storage_path).read_bytes()
    if (hashlib.sha256(raw).hexdigest() != asset.sha256
            or p["source_sha256"] != asset.sha256
            or image_gate.identity(image_gate.normalize(raw)) != p["identity"]):
        raise PermissionError("画像判定の取得画像・入力SHA・版が一致しません")
    saved = Path(p["result_path"]).read_bytes()
    if hashlib.sha256(saved).hexdigest() != p["result_sha256"]:
        raise PermissionError("画像判定artifactが変更されています")
    result = json.loads(saved)
    people = (result.get("result") or {}).get("real_people", "uncertain")
    if result.get("error"):
        people = "uncertain"
    policy = region_policy.reference(segment)
    if policy is None:
        raise PermissionError("OneFormerの人物画素根拠が必要です")
    payload = segment.parameters["payload"]
    prep = _run(session, asset_id, payload["input_run_id"], "prep")
    prep_job = session.scalar(select(Job).where(Job.run_id == prep.id))
    if (payload["input_path"] not in prep.output_paths.values()
            or prep_job.payload.get("input_path") != asset.storage_path
            or prep.parameters.get("input_sha256") != asset.sha256):
        raise PermissionError("prepと取得画像の由来が一致しません")
    region_policy.load_masks({**payload, "region_run_id": str(segment.id),
                              "region_policy": policy})
    with Image.open(policy["semantic"]["path"]) as image:
        semantic = np.array(image)
    record = policy["exclusions"]["person"]
    with Image.open(record["path"]) as image:
        mask = np.array(image)
    if not np.array_equal(mask != 0, semantic == 12):
        raise PermissionError("人物maskとsemantic person画素が一致しません")
    return {"asset_id": str(asset_id), "policy": POLICY, "policy_hash": digest(POLICY),
            "subject_id": str(asset.subject_id) if asset.subject_id else None,
            "source_sha256": asset.sha256, "image_gate_run_id": str(gate.id),
            "image_gate_hash": digest(p),
            "image_gate_input_sha256": p["identity"]["input_sha256"],
            "analysis_domain": p["verdict"]["analysis_domain"],
            "region_policy_run_id": str(segment.id), "region_policy_hash": digest(policy),
            "input_path": payload["input_path"], "input_sha256": policy["input_sha256"],
            "size": policy["size"], "person_mask_sha256": record["sha256"],
            "real_people": people, "semantic_person_pixels": int((semantic == 12).sum())}


def write(queue, asset_id, gate_id, segment_id, *, code_version, input_run_id=None,
          reviewer=None, real_people=None, presented_source_sha256=None, note=None):
    """A/Bを固定したreview runを追加する。旧Asset/quality/判定は書き換えない。

    人の訂正は元privacy run・取得解像度画像の提示SHA・確認者・所見を必要とする。
    訂正できるのは画像上の実在人物根拠だけで、画素根拠や保留方針を上書きしない。
    呼出し側は提示済みの画像への番号返信だけをこの引数へ変換する。
    """
    asset_id = uuid.UUID(str(asset_id))
    with queue._transaction() as session:
        retention.lock(session)
        data = evidence(session, asset_id, gate_id, segment_id)
        if input_run_id:
            original = _run(session, asset_id, input_run_id, "review", "privacy_review")
            _not_corrected(session, original)
            before = original.parameters["evidence"]
            if (any(before[k] != data[k] for k in data if k != "real_people")
                    or not reviewer or not note or real_people not in {
                        "present", "absent", "uncertain"}
                    or presented_source_sha256 != data["source_sha256"]):
                raise ValueError("訂正元・提示画像・確認者・所見が一致しません")
            data["real_people"] = real_people
        elif any(v is not None for v in (reviewer, real_people, presented_source_sha256, note)):
            raise ValueError("人の訂正には元privacy runが必要です")
        asset = session.get(Asset, asset_id)
        info = RunInfo(asset.license_class, code_version, asset.taxonomy_version, "privacy",
                       {"kind": "privacy_review", "evidence": data,
                        "method": "human" if input_run_id else "policy",
                        "input_run_id": str(input_run_id) if input_run_id else None,
                        "reviewer": reviewer, "note": note,
                        "presented_source_sha256": presented_source_sha256,
                        "verdict": decision(data["real_people"], data["semantic_person_pixels"])})
    payload = {"kind": "privacy_review", "parameters": info.parameters,
               "license_class": info.license_class, "code_version": code_version,
               "taxonomy_version": info.taxonomy_version}
    job_id = queue.enqueue("review", asset_id, digest(payload), payload)
    claim = queue.claim(("review",), job_ids=[job_id])
    if claim is None:
        with queue._transaction() as session:
            job = session.get(Job, job_id)
            if job.status == "succeeded":
                return job.run_id
        raise RuntimeError("人物review jobは別の担当が処理中です")

    prepared = prepare(claim)
    return queue.complete(claim, prepared.info,
                          lambda session, run: register(session, run, prepared.data))


def prepare(claim):
    """共通review workerから再開できる、通信・ファイル書込みなしの準備処理。"""
    p = claim.payload
    return Prepared(RunInfo(p["license_class"], p["code_version"], p["taxonomy_version"],
                            "privacy", p["parameters"]), {"asset_id": str(claim.asset_id)})


def register(session, run, data):
    """完了取引で二つの根拠と訂正元を再検証して依存関係を固定する。"""
    retention.lock(session)
    p = run.parameters
    saved = p["evidence"]
    current = evidence(session, data["asset_id"], saved["image_gate_run_id"],
                       saved["region_policy_run_id"])
    if p["input_run_id"]:
        original = _run(session, data["asset_id"], p["input_run_id"], "review", "privacy_review")
        _not_corrected(session, original)
        current["real_people"] = saved["real_people"]
    if current != saved:
        raise PermissionError("人物reviewの入力が変更されています")
    parents = {uuid.UUID(saved["image_gate_run_id"]), uuid.UUID(saved["region_policy_run_id"])}
    if p["input_run_id"]:
        parents.add(uuid.UUID(p["input_run_id"]))
    session.add_all(ProcessingRunInput(run_id=run.id, input_run_id=parent) for parent in parents)


def _review(session, asset_id, run_id):
    asset_id = uuid.UUID(str(asset_id))
    run = _run(session, asset_id, run_id, "review", "privacy_review")
    _not_corrected(session, run)
    p = run.parameters
    data = p["evidence"]
    current = evidence(session, asset_id, data["image_gate_run_id"], data["region_policy_run_id"])
    if p["method"] == "human":
        if (not p["reviewer"] or not p["note"]
                or p["presented_source_sha256"] != current["source_sha256"]):
            raise PermissionError("人の確認根拠がありません")
        current["real_people"] = data["real_people"]
    verdict = decision(data["real_people"], data["semantic_person_pixels"])
    if current != data or p["verdict"] != verdict:
        raise PermissionError("人物確認の入力・policyが変更されています")
    return run


def selection(session, asset_id, run_id):
    """採用可能な明示privacy runを共有selectionへ変換する。訂正済みrunは拒否する。"""
    run = _review(session, asset_id, run_id)
    p = run.parameters
    data = p["evidence"]
    if p["verdict"]["decision"] != "accepted":
        raise PermissionError("人物確認は保留です")
    row = image_gate.selection(session, asset_id, data["image_gate_run_id"])
    row.update({k: data[k] for k in FIELDS if k in data})
    row.update(privacy_review_run_id=str(run.id), privacy_review_hash=digest(p))
    return row


def evaluation_input(session, samples):
    """D用の私有入力を固定する。samplesは(asset_id, review_run_id, group)の列。

    groupはrandom_old/random_new/challenge。抽出はD側で結果を見る前に行う。
    保留も残し、入力SHAの重複・古い訂正を拒否する。返すhashに全根拠・所見を含む。
    この戻り値は画像や個別IDを含む私有情報であり、Git・公開出力へ保存しない。
    """
    rows, seen = [], set()
    for asset_id, run_id, group in samples:
        if group not in {"random_old", "random_new", "challenge"}:
            raise ValueError("無作為cohortと難例を区別してください")
        run = _review(session, asset_id, run_id)
        sha = run.parameters["evidence"]["source_sha256"]
        if sha in seen:
            raise ValueError("評価入力の画像SHAが重複しています")
        seen.add(sha)
        rows.append({"group": group, "privacy_review_run_id": str(run.id),
                     "privacy_review_hash": digest(run.parameters),
                     "review": run.parameters})
    if not rows:
        raise ValueError("評価入力が空です")
    manifest = {"policy": POLICY, "policy_hash": digest(POLICY),
                "samples": sorted(rows, key=lambda r: (r["group"], r["privacy_review_run_id"]))}
    return {**manifest, "hash": digest(manifest)}


def check_selection(session, asset_id, payload):
    """新policyの全段階でrun・hash・寸法を検証する。旧qualityへ代替しない。"""
    expected = selection(session, asset_id, payload["privacy_review_run_id"])
    if payload.get("contract") != "image-review-v1" or any(
            payload.get(k) != expected[k] for k in FIELDS):
        raise PermissionError("人物確認のrun・SHA・寸法が選択と一致しません")
    if payload.get("person_mask"):
        raise PermissionError("人物mask救済は許可されていません")
    if payload.get("region_run_id", expected["region_policy_run_id"]) != expected[
        "region_policy_run_id"
    ]:
        raise PermissionError("人物確認と領域runが一致しません")


def is_new(payload):
    """欠損した新版参照を旧policyとして通さないための判別。"""
    return payload.get("contract") == "image-review-v1" or any(
        payload.get(k) is not None for k in (
            "image_gate_run_id", "privacy_review_run_id", "region_policy_run_id"))
