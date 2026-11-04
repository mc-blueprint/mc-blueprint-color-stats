"""collectジョブの投入、原本準備、完了取引内の出典・画像登録。"""

import hashlib
import json
import logging
import shutil
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from colorstats.collect import Candidate, SearchRequest
from colorstats.collect.commons import CommonsAdapter, check_commons_policy
from colorstats.collect.http import MeasurementLimit
from colorstats.collect.openverse import OpenverseAdapter
from colorstats.collect.policy import license_class, load_policy
from colorstats.queue import RunInfo
from colorstats.queue.worker import Prepared
from colorstats.schema.models import Asset, Source
from colorstats.store import Storage, temporary_path

MIME_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/tiff": "tif",
    "image/gif": "gif",
}
logger = logging.getLogger(__name__)


def adapter_for(provider, policy):
    """providerに対応するアダプターを返し、その利用ポリシーを検証する。通信は行わない。"""
    if provider == "wikimedia_commons":
        check_commons_policy(policy)
        return CommonsAdapter(policy)
    if provider == "openverse":
        return OpenverseAdapter(policy)
    raise ValueError("未登録の収集アダプターです")


def enqueue_collect(
    queue,
    request: SearchRequest,
    *,
    policy_path: Path,
    storage_config: Path,
    host: str,
    domain: str,
    code_version: str,
    taxonomy_version: str,
):
    """検索1ページを投入する。設定内容・検索対象込みのハッシュで重複を防ぐ。

    ポリシーはpayloadへ固定する。保存先設定は絶対パスと内容ハッシュを保存し、
    ワーカーで変更を検出する。保存先は実行ホストからローカル参照可能であること。
    """
    if domain not in ("real_building", "real_terrain"):
        raise ValueError("収集は実建築・地形が対象です")
    policy = load_policy(policy_path, request.provider)
    adapter_for(request.provider, policy)
    payload = {
        "request": asdict(request),
        "policy": policy,
        "storage_config": str(storage_config.resolve()),
        "storage_hash": hashlib.sha256(storage_config.read_bytes()).hexdigest(),
        "host": host,
        "domain": domain,
        "code_version": code_version,
        "taxonomy_version": taxonomy_version,
    }
    config_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    return queue.enqueue("collect", None, config_hash, payload)


def prepare(
    claim,
    *,
    decide: Callable[[SearchRequest, Candidate], str | None] | None = None,
    discard: Callable[[SearchRequest, Candidate], None] | None = None,
    observer=None,
):
    """原本準備を行う。decideは取得直前に順次呼び、除外理由または採用のNoneを返す。

    省略時は許可候補を全採用する。層・集中上限の判断と同一バッチ内の予約は呼出し側の責務。
    discardは採用後の原本取得4xx除外時に呼び、次候補の判断前に予約を解放できる。
    測定枠による正常停止では取得成功分を返す。通常の例外は伝播し、一時出力を清掃する。
    observerへ途中経過を渡す。確定ファイル・DBの登録は行わない。
    """
    payload = claim.payload
    config = Path(payload["storage_config"])
    if hashlib.sha256(config.read_bytes()).hexdigest() != payload["storage_hash"]:
        raise ValueError("投入後に保存先設定が変更されました")
    storage = Storage(config)
    request = SearchRequest(**payload["request"])
    adapter = adapter_for(request.provider, payload["policy"])
    files, records, skipped = [], [], []
    parameters = {
        "request": asdict(request), "effective": {}, "next_offset": None,
        "api_next_offset": None, "skipped": skipped, "candidates": [],
        "policy": payload["policy"], "search_complete": False,
    }

    def observe(event, value=1):
        if event == "search":
            parameters.update(value)
        elif event == "candidate":
            parameters["candidates"].append(value)
            if value["reason"]:
                entry = {k: value[k] for k in ("source_url", "original_url", "rank", "reason")}
                if entry not in skipped:
                    skipped.append(entry)
        elif event == "exclusion" and value not in skipped:
            skipped.append(value)
        if observer is not None:
            observer(event, value)

    if observer is not None:
        adapter.observer = observe
    temporary = None
    try:
        observe("search", parameters.copy())
        try:
            result = adapter.search(request)
        except MeasurementLimit as error:
            if observer is None:
                raise
            parameters.update(stop_reason=str(error), next_offset=None)
            candidates = []
        else:
            parameters.update(effective=result.parameters, next_offset=result.next_offset,
                              api_next_offset=result.next_offset, search_complete=True)
            observe("search_responses")
            candidates = result.candidates
        observe("search", parameters.copy())
        for candidate in candidates:
            category = license_class(payload["policy"], candidate.license)
            extension = MIME_EXTENSIONS.get(candidate.mime)
            reason = (
                "restricted"
                if category == "restricted"
                else candidate.exclusion_reason or ("mime" if extension is None else None)
            )
            if reason is None and decide is not None:
                reason = decide(request, candidate)
            if reason is not None:
                entry = {"source_url": candidate.source_url, "original_url": candidate.original_url,
                         "rank": candidate.rank, "reason": reason}
                if entry not in skipped:
                    skipped.append(entry)
                observe("exclusion", entry)
                logger.info(
                    "候補を除外: %s rank=%s reason=%s", candidate.source_url, candidate.rank, reason
                )
                continue
            # ハッシュ確定前もraw媒体上に試行固有ファイルを置く。
            seed = hashlib.sha256(candidate.original_url.encode()).hexdigest()
            provisional = storage.resolve(f"raw/{seed[:2]}/{seed}.{extension}").local_path(
                payload["host"]
            )
            temporary = temporary_path(provisional, str(claim.token))
            parameters["download_candidate"] = {
                "source_url": candidate.source_url, "original_url": candidate.original_url,
                "rank": candidate.rank,
            }
            observe("search", parameters.copy())
            try:
                adapter.download(candidate, temporary)
            except MeasurementLimit as error:
                if observer is None:
                    raise
                temporary.unlink(missing_ok=True)
                temporary = None
                if discard is not None:
                    discard(request, candidate)
                parameters.update(stop_reason=str(error), next_offset=None)
                break
            except HTTPError as error:
                if not 400 <= error.code < 500 or error.code == 429:
                    raise
                error.close()
                temporary.unlink(missing_ok=True)
                temporary = None
                if discard is not None:
                    discard(request, candidate)
                reason = f"download_http_{error.code}"
                skipped.append(
                    {
                        "source_url": candidate.source_url,
                        "original_url": candidate.original_url,
                        "rank": candidate.rank,
                        "reason": reason,
                    }
                )
                observe("exclusion", skipped[-1])
                logger.info(
                    "原本取得候補を除外: %s rank=%s reason=%s",
                    candidate.source_url,
                    candidate.rank,
                    reason,
                )
                continue
            with temporary.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if observer is not None:
                observer("downloads", 1)
                observer("download_bytes", temporary.stat().st_size)
            logical = f"raw/{digest[:2]}/{digest}.{extension}"
            target = storage.resolve(logical).local_path(payload["host"])
            if temporary.parent != target.parent:
                moved = temporary_path(target, str(claim.token))
                try:
                    # rawが複数媒体に分かれる場合も対応する。
                    with temporary.open("rb") as src, moved.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                except BaseException:
                    moved.unlink(missing_ok=True)
                    raise
                temporary.unlink()
                temporary = moved
            if any(existing == target for _, existing in files):
                temporary.unlink()
            else:
                files.append((temporary, target))
            temporary = None
            records.append(
                {
                    "candidate": asdict(candidate),
                    "license_class": category,
                    "sha256": digest,
                    "logical_path": logical,
                    "target": str(target),
                    "retrieved_at": datetime.now(UTC),
                }
            )
        observe("search", parameters.copy())
        classes = {r["license_class"] for r in records} - {"open"}
        run_class = (
            next(iter(classes)) if len(classes) == 1 else "restricted" if classes else "open"
        )
        info = RunInfo(
            run_class,
            payload["code_version"],
            payload["taxonomy_version"],
            payload["host"],
            parameters,
        )
        return Prepared(info, {"records": records, "payload": payload}, files)
    except BaseException as error:
        parameters.update(failure=type(error).__name__, next_offset=None)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        for path, _ in files:
            path.unlink(missing_ok=True)
        observe("search", parameters.copy())
        raise
    finally:
        adapter.finish()


def register(session, run, data):
    """キューの所有権付き完了取引内で登録する。ファイルI/Oとcommitは行わない。"""
    payload = data["payload"]
    asset_ids = []
    for record in data["records"]:
        candidate = record["candidate"]
        attribution = candidate["attribution"]
        source_id = session.scalar(
            insert(Source)
            .values(
                url=candidate["source_url"],
                site=payload["request"]["provider"],
                author=candidate["author"],
                license=candidate["license"],
                license_class=record["license_class"],
                attribution=attribution,
                retrieved_at=record["retrieved_at"],
                policy=payload["policy"],
            )
            .on_conflict_do_nothing(index_elements=[Source.url])
            .returning(Source.id)
        )
        if source_id is None:
            source_id = session.scalar(
                select(Source.id).where(Source.url == candidate["source_url"])
            )
        asset = Asset(
            source_id=source_id,
            collected_title=candidate["title"],
            collected_location=candidate["location"],
            url=candidate["original_url"],
            sha256=record["sha256"],
            width=candidate["width"],
            height=candidate["height"],
            storage_path=run.output_paths[record["target"]],
            domain=payload["domain"],
            license_class=record["license_class"],
            search_provider=payload["request"]["provider"],
            search_query=payload["request"]["query"],
            search_parameters={
                "request": payload["request"],
                "effective": run.parameters["effective"],
            },
            result_rank=candidate["rank"],
            result_page=candidate["page"],
            retrieved_at=record["retrieved_at"],
            taxonomy_version=payload["taxonomy_version"],
            scene_attributes={},
            quality={
                "description": candidate["description"],
                "metadata": candidate["metadata"],
                "license": candidate["license"],
                "license_url": candidate["license_url"],
                "author": candidate["author"],
                "attribution": attribution,
                "source_policy": payload["policy"],
                "logical_path": record["logical_path"],
            },
        )
        session.add(asset)
        session.flush()
        asset_ids.append(str(asset.id))
    run.parameters = {**run.parameters, "asset_ids": asset_ids}
