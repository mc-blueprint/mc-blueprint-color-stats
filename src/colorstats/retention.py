"""新規入力の保持期限、利用停止、参照解除と物理削除を管理する。"""

import hashlib
import socket
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import or_, select, text

from colorstats.rights import analysis_review_reasons
from colorstats.schema.models import (
    Asset,
    Job,
    ProcessingRun,
    Region,
    Retention,
    RetentionFile,
    RetentionStop,
    Source,
)


def lock(session):
    """収集確定・削除受付・参照更新を同じ取引ロックで直列化する。"""
    session.execute(text("SELECT pg_advisory_xact_lock(88, 1)"))


def register_file(session, asset_id, host, path, kind):
    """内部ファイルの依存を登録する。呼出し元がlockを保持しcommitする。"""
    if kind not in {"raw", "derived", "mask", "cvat", "replica", "cache", "backup"}:
        raise ValueError("未知の保持ファイル種別です")
    candidate = Path(path)
    if candidate.is_symlink() or any(parent.is_symlink() for parent in candidate.parents):
        raise ValueError("保持対象にはsymlinkを指定できません")
    path = str(candidate.resolve())
    assert_usable(session, asset_id, images=True)
    if session.scalar(select(RetentionFile.id).where(
        RetentionFile.asset_id == asset_id, RetentionFile.host == host,
        RetentionFile.path == path,
    )) is None:
        session.add(RetentionFile(asset_id=asset_id, host=host, path=path, kind=kind))


def register_asset(session, asset, policy, host):
    """取得時の短い保持条件を固定する。既存画像の遡及登録には使用しない。"""
    days = policy.get("retention", {})
    expiry = asset.retrieved_at + timedelta(days=min(days.get("raw_days", 30), 30))
    if value := asset.quality.get("retention_until"):
        expiry = min(expiry, datetime.fromisoformat(value))
    asset.quality = {**asset.quality, "retention_until": expiry.isoformat()}
    session.add(Retention(
        asset_id=asset.id, expires_at=expiry,
        backup_until=expiry + timedelta(days=min(days.get("backup_days", 30), 30)),
    ))
    register_file(session, asset.id, host, asset.storage_path, "raw")


def assert_usable(session, asset_id, *, images=False, now=None):
    """現時点の利用根拠を確認する。画像期限だけでは数値統計を失効させない。

    受付と競合する書込み側は先にlockを取得する。利用不可はPermissionError。
    """
    now = now or datetime.now(UTC)
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise ValueError("対象画像が見つかりません")
    source = session.get(Source, asset.source_id)
    tombstone = session.scalar(select(RetentionStop.id).where(
        RetentionStop.provider == source.site, RetentionStop.source_url == source.url,
        RetentionStop.target_url.in_(("", asset.url)),
    ))
    record = session.scalar(select(Retention).where(Retention.asset_id == asset.id))
    _assert_current(asset, source, record, tombstone, images=images, now=now)


def _assert_current(asset, source, record, tombstone, *, images, now):
    rights = asset.quality.get("rights", {})
    if tombstone:
        raise PermissionError("削除台帳に登録済みの入力です")
    if any(p.get("use_stopped") or p.get("deletion_requested")
           for p in (rights, source.policy)):
        raise PermissionError("入力の新規利用は停止されています")
    if record is not None and asset.license_class == "analysis_only" and (
        analysis_review_reasons(rights, now=now)
        or analysis_review_reasons(source.policy, now=now)
    ):
        raise PermissionError("解析専用入力の利用根拠が無効です")
    if record is not None and (record.stopped_at or (images and record.expires_at <= now)):
        raise PermissionError("入力の利用停止または画像保持期限切れです")


def check_acquisition(session, provider, source_url, original_url):
    """受付済みsource/原画像URLの再取得を拒否する。氏名では検索しない。"""
    if session.scalar(select(RetentionStop.id).where(or_(
        (RetentionStop.provider == provider) & (RetentionStop.source_url == source_url)
        & RetentionStop.target_url.in_(("", original_url)),
        RetentionStop.target_url == original_url,
    ))):
        raise PermissionError("削除台帳に登録済みの出典です")
    stopped = session.scalar(select(Source.id).where(
        Source.site == provider, Source.url == source_url,
        or_(Source.policy["use_stopped"].as_boolean() == True,  # noqa: E712
            Source.policy["deletion_requested"].as_boolean() == True),  # noqa: E712
    ))
    previous = session.scalars(select(Asset).where(or_(
        Asset.url == original_url,
        Asset.source_id.in_(select(Source.id).where(
            Source.site == provider, Source.url == source_url,
        )),
    ))).all()
    if stopped:
        raise PermissionError("削除受付済みの出典です")
    for asset in previous:
        assert_usable(session, asset.id)


def stop(session, *, source_url=None, provider=None, native_id=None, url=None,
         request_url, reason="deletion_request", now=None):
    """管理用受付。source URL、provider/native ID、原画像URLのいずれかで指定する。

    GitHub Issue URLと受付時刻を記録する。source URL指定は出典全体、他は該当画像だけ停止する。
    呼出し元が取引をcommitする。未知対象はValueError。既存画像は物理削除しない。
    """
    if reason not in {"deletion_request", "rights_revoked", "rejected"}:
        raise ValueError("未知の停止理由です")
    if not request_url.startswith(
        "https://github.com/mc-blueprint/mc-blueprint-color-stats/issues/"
    ):
        raise ValueError("受付Issue URLが必要です")
    lock(session)
    now = now or datetime.now(UTC)
    if source_url:
        query = select(Asset).join(Source).where(Source.url == source_url)
    elif provider and native_id:
        query = select(Asset).where(
            Asset.search_provider == provider,
            Asset.quality["metadata"]["native_id"].as_string() == native_id,
        )
    elif url:
        query = select(Asset).where(Asset.url == url)
    else:
        raise ValueError("source URL、provider/native ID、原画像URLが必要です")
    assets = session.scalars(query).all()
    if not assets:
        raise ValueError("対象画像が見つかりません")
    source_ids = {asset.source_id for asset in assets}
    sources = {s.id: s for s in session.scalars(select(Source).where(Source.id.in_(source_ids)))}
    source_wide = bool(source_url) and reason != "rejected"
    for asset in assets:
        source = sources[asset.source_id]
        target_url = "" if source_wide else asset.url
        if source_wide:
            source.policy = {**source.policy, "use_stopped": True}
        if session.scalar(select(RetentionStop.id).where(
            RetentionStop.provider == source.site, RetentionStop.source_url == source.url,
            RetentionStop.target_url == target_url,
        )) is None:
            session.add(RetentionStop(provider=source.site, source_url=source.url,
                                      target_url=target_url, details={
                "received_at": now.isoformat(), "request_url": request_url, "reason": reason,
                "original_url": asset.url,
            }))
    for asset in assets:
        asset.quality = {**asset.quality, "rights": {
            **asset.quality.get("rights", {}), "use_stopped": True,
        }}
        record = session.scalar(select(Retention).where(Retention.asset_id == asset.id))
        if record is None:
            continue
        if record.stopped_at is None:
            record.stopped_at, record.reason, record.request_url = now, reason, request_url
        policy = asset.quality.get("source_policy", {}).get("retention", {}) | (
            asset.quality.get("rights", {}).get("retention", {})
        )
        current = session.get(Source, asset.source_id).policy.get("retention", {})
        key = "rejected_days" if reason == "rejected" else "deletion_request_days"
        record.expires_at = min(record.expires_at, now + timedelta(
            days=min(policy.get(key, 7), current.get(key, 7), 7),
        ))
        record.backup_until = min(record.backup_until, now + timedelta(
            days=min(policy.get("backup_days", 30), current.get("backup_days", 30), 30),
        ))
    return [str(asset.id) for asset in assets]


def cleanup(session, *, host, now=None):
    """期限到来分を参照解除後に消す。各呼出しをcommitして監査状態を保存する。

    host上の登録済み通常ファイルだけが対象。共有参照と既存画像は保護する。
    I/O失敗はerrorへ記録し再実行可能。backupは期限到来後に同じ手順で消す。
    """
    lock(session)
    now = now or datetime.now(UTC)
    records = {r.asset_id: r for r in session.scalars(select(Retention))}
    files = session.scalars(select(RetentionFile).where(
        RetentionFile.host == host, RetentionFile.deleted_at.is_(None),
    ).order_by(RetentionFile.path)).all()
    for file in files:
        record = records[file.asset_id]
        expiry = record.backup_until if file.kind == "backup" else record.expires_at
        if expiry > now:
            continue
        # 先に論理参照を外す。失敗なら物理ファイルには触れない。
        asset = session.get(Asset, file.asset_id)
        if asset.storage_path == file.path:
            asset.storage_path = ""
        for region in session.scalars(select(Region).where(
            Region.asset_id == file.asset_id, Region.mask_path == file.path,
        )):
            region.mask_path = None
        file.released_at = file.released_at or now
        session.flush()
        shared = session.scalar(select(RetentionFile.id).where(
            RetentionFile.host == host, RetentionFile.path == file.path,
            RetentionFile.id != file.id, RetentionFile.released_at.is_(None),
        ))
        legacy = session.scalar(select(Asset.id).where(Asset.storage_path == file.path))
        legacy_region = session.scalar(select(Region.id).join(
            ProcessingRun, Region.processing_run_id == ProcessingRun.id,
        ).where(or_(
            Region.mask_path == file.path,
            ProcessingRun.output_paths["masks"].as_string() + "/" + Region.mask_path == file.path,
        )).limit(1))
        legacy_run = session.scalar(select(ProcessingRun.id).join(
            Job, Job.run_id == ProcessingRun.id,
        ).outerjoin(Retention, Retention.asset_id == Job.asset_id).where(
            Retention.id.is_(None), Job.asset_id.is_not(None),
            text("EXISTS (SELECT 1 FROM jsonb_each_text(processing_run.output_paths) p "
                 "WHERE p.value = :path)"),
        ).params(path=file.path).limit(1))
        if shared or legacy or legacy_region or legacy_run:
            file.error = "shared_reference"
            continue
        try:
            path = Path(file.path)
            if path.resolve() != path or path.is_symlink() or (
                path.exists() and not path.is_file()
            ):
                raise OSError("通常ファイル以外は削除しません")
            path.unlink(missing_ok=True)
            for released in session.scalars(select(RetentionFile).where(
                RetentionFile.host == host, RetentionFile.path == file.path,
                RetentionFile.released_at.is_not(None),
            )):
                released.deleted_at, released.error = now, None
        except OSError as error:
            file.error = str(error)


def export_tombstones(session):
    """DB backupと別保管する停止台帳。復元前に必ず最新版を取得する。"""
    return [{"provider": s.provider, "source_url": s.source_url,
             "target_url": s.target_url, "details": s.details}
            for s in session.scalars(select(RetentionStop))]


def apply_tombstones(session, entries):
    """復元DBをworkerへ開放する前に停止を再適用する。commitは呼出し元。"""
    for entry in entries:
        lock(session)
        source = session.scalar(select(Source).where(Source.url == entry["source_url"]))
        matching = source is not None and session.scalar(select(Asset.id).where(
            Asset.source_id == source.id,
            Asset.url == entry["target_url"] if entry["target_url"] else True,
        ).limit(1))
        if matching:
            target = {"url": entry["target_url"]} if entry["target_url"] else {
                "source_url": source.url,
            }
            stop(session, **target, request_url=entry["details"]["request_url"],
                 reason=entry["details"]["reason"],
                 now=datetime.fromisoformat(entry["details"]["received_at"]))
        elif session.scalar(select(RetentionStop.id).where(
            RetentionStop.provider == entry["provider"],
            RetentionStop.source_url == entry["source_url"],
            RetentionStop.target_url == entry["target_url"],
        )) is None:
            session.add(RetentionStop(**entry))
            if source is not None and not entry["target_url"]:
                source.policy = {**source.policy, "use_stopped": True}


def _selection_rows(session, selection):
    ids = [uuid.UUID(item["asset_id"]) for item in selection["assets"]]
    stopped = select(RetentionStop.id).where(
        RetentionStop.provider == Source.site, RetentionStop.source_url == Source.url,
        or_(RetentionStop.target_url == "", RetentionStop.target_url == Asset.url),
    ).exists()
    rows = session.execute(select(Asset, Source, Retention, stopped).join(
        Source, Asset.source_id == Source.id,
    ).outerjoin(Retention, Retention.asset_id == Asset.id).where(Asset.id.in_(ids))).all()
    if len(rows) != len(ids):
        raise ValueError("選択入力がDBにありません")
    return rows


def check_selection(session, selection, *, images=False):
    """snapshot選択を現行台帳で再確認する。旧snapshotを上書きしない。"""
    now = datetime.now(UTC)
    rows = _selection_rows(session, selection)
    for asset, source, record, tombstone in rows:
        _assert_current(asset, source, record, tombstone, images=images, now=now)


def rebuild_selection(session, selection):
    """内部snapshotの依存索引から停止入力を除いた新版selectionを返す。旧版は変更しない。"""
    allowed = set()
    now = datetime.now(UTC)
    for asset, source, record, tombstone in _selection_rows(session, selection):
        try:
            _assert_current(asset, source, record, tombstone, images=False, now=now)
        except PermissionError:
            continue
        allowed.add(str(asset.id))
    return {**selection, "assets": [item for item in selection["assets"]
                                   if item["asset_id"] in allowed]}


def review_privacy(session, asset_id, *, reviewer, subject, person_mask=None, host=None):
    """内部目視確認を記録する。人物・要配慮主体は採用せず、写り込みは除外maskを固定する。

    subjectはbuilding/terrainのみ。maskは解析画像と同寸の人物画素を非ゼロとするPNG。
    人物がいなければNone。レビュー担当が原画像・縮小画像の両方を確認する。
    """
    lock(session)
    assert_usable(session, asset_id, images=True)
    if subject not in {"building", "terrain"} or not reviewer:
        raise ValueError("人物・要配慮主体は採用できません。内部確認者が必要です")
    asset = session.get(Asset, asset_id)
    mask = str(Path(person_mask).absolute()) if person_mask else None
    asset.quality = {**asset.quality, "privacy_review": {
        "reviewer": reviewer, "subject": subject, "reviewed_at": datetime.now(UTC).isoformat(),
        "person_mask": mask,
        "mask_sha256": hashlib.sha256(Path(mask).read_bytes()).hexdigest() if mask else None,
    }}
    if mask:
        register_file(session, asset_id, host or socket.gethostname(), mask, "mask")


def check_privacy(session, asset_id, payload):
    """新規収集分の色集計に目視確認と人物除外maskの固定を要求する。"""
    if session.scalar(select(Retention.id).where(Retention.asset_id == asset_id)) is None:
        return
    review = session.get(Asset, asset_id).quality.get("privacy_review", {})
    if not review.get("reviewer") or review.get("subject") not in {"building", "terrain"}:
        raise PermissionError("人物・要配慮情報の内部確認が必要です")
    if payload.get("person_mask") != review.get("person_mask"):
        raise PermissionError("人物除外maskが確認記録と一致しません")
    if review.get("person_mask") and hashlib.sha256(
        Path(review["person_mask"]).read_bytes(),
    ).hexdigest() != review["mask_sha256"]:
        raise PermissionError("人物除外maskが変更されています")
