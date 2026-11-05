"""ジョブの取得・更新は短いトランザクション、結果登録は完了確定と同一取引。"""

import socket
import uuid
from collections.abc import Callable, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from colorstats import retention
from colorstats.rights import combine_license
from colorstats.schema.models import Asset, Job, ProcessingRun, Source

STAGES = ("collect", "prep", "segment", "shade", "color", "review", "aggregate")


class LeaseLost(RuntimeError):
    """期限切れまたは別試行への移譲により書込み権を失った。"""


@dataclass(frozen=True)
class Claim:
    id: uuid.UUID
    token: uuid.UUID
    stage: str
    asset_id: uuid.UUID | None
    config_hash: str
    payload: dict
    attempt: int
    started_at: datetime


@dataclass(frozen=True)
class RunInfo:
    license_class: str
    code_version: str
    taxonomy_version: str
    node: str
    parameters: dict
    model_name: str | None = None
    weights_hash: str | None = None


class Queue:
    """PostgreSQL 16専用。各メソッドが独立したSessionと取引を所有する。"""

    def __init__(
        self, engine: Engine, lease: timedelta = timedelta(minutes=10), *, timeout: float = 5
    ):
        if lease.total_seconds() <= 0:
            raise ValueError("リースは正の期間が必要です")
        self.engine = engine
        self.lease = lease
        if timeout <= 0:
            raise ValueError("取引の待機上限は正の秒数が必要です")
        self.timeout = timeout

    @contextmanager
    def _transaction(self):
        with Session(self.engine) as session, session.begin():
            milliseconds = str(max(1, int(self.timeout * 1000)))
            session.execute(
                text("SELECT set_config('statement_timeout', :timeout, true), "
                     "set_config('idle_in_transaction_session_timeout', :timeout, true)"),
                {"timeout": milliseconds},
            )
            yield session

    def enqueue(
        self, stage: str, asset_id: uuid.UUID | None, config_hash: str, payload: dict
    ) -> uuid.UUID:
        """同じキーは既存IDを返す。payload差異は拒否し、完了・失敗を再開しない。

        assetを持たないcollect/aggregateはasset_id=Noneとし、対象を含む設定ハッシュで
        実行単位を区別する。payloadは秘密情報を含まないJSON辞書。
        """
        with self._transaction() as session:
            job_id = session.scalar(
                insert(Job)
                .values(
                    stage=stage, asset_id=asset_id, stage_config_hash=config_hash, payload=payload
                )
                .on_conflict_do_nothing(constraint="uq_job_key")
                .returning(Job.id)
            )
            if job_id is not None:
                return job_id
            job = session.scalars(
                select(Job).where(
                    Job.stage == stage,
                    Job.asset_id == asset_id,
                    Job.stage_config_hash == config_hash,
                )
            ).one()
            if job.payload != payload:
                raise ValueError("同じジョブキーに異なるpayloadは指定できません")
            return job.id

    def claim(
        self, stages: Sequence[str], *, job_ids: Sequence[uuid.UUID] | None = None
    ) -> Claim | None:
        """指定stageから1件取得する。job_ids指定時はその集合に限定する。

        期限切れも1失敗と数え、3試行で打ち切る。空集合では取得しない。
        """
        with self._transaction() as session:
            while True:
                job = session.scalars(
                    select(Job)
                    .where(
                        Job.stage.in_(stages),
                        Job.id.in_(job_ids) if job_ids is not None else True,
                        or_(
                            (Job.status == "pending")
                            & (Job.available_at <= func.clock_timestamp()),
                            (Job.status == "running") & (Job.lease_until <= func.clock_timestamp()),
                        ),
                    )
                    .order_by(Job.created_at, Job.id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                ).first()
                if job is None:
                    return None
                if job.status == "running":
                    job.failure_reason = "リース期限切れ"
                if job.attempts >= 3:
                    job.status = "failed"
                    job.lease_token = job.lease_until = None
                    session.flush()
                    continue
                job.status = "running"
                job.attempts += 1
                job.lease_token = uuid.uuid4()
                started_at = session.scalar(select(func.clock_timestamp()))
                job.lease_until = started_at + self.lease
                session.flush()
                return Claim(
                    job.id,
                    job.lease_token,
                    job.stage,
                    job.asset_id,
                    job.stage_config_hash,
                    job.payload,
                    job.attempts,
                    started_at,
                )

    def _owned(self, session: Session, claim: Claim) -> Job:
        job = session.scalars(select(Job).where(Job.id == claim.id).with_for_update()).one()
        now = session.scalar(select(func.clock_timestamp()))
        if job.status != "running" or job.lease_token != claim.token or job.lease_until <= now:
            raise LeaseLost("ジョブのリースを失いました")
        return job

    def renew(self, claim: Claim) -> None:
        """有効な所有権のみ延長する。期限切れはLeaseLost。"""
        with self._transaction() as session:
            job = self._owned(session, claim)
            if job.asset_id is not None:
                retention.assert_usable(session, job.asset_id, images=True)
            job.lease_until = session.scalar(select(func.clock_timestamp())) + self.lease

    def fail(self, claim: Claim, reason: str) -> None:
        """失敗理由を保存し、3試行未満はpendingへ戻す。期限切れはLeaseLost。"""
        with self._transaction() as session:
            job = self._owned(session, claim)
            job.status = "failed" if job.attempts >= 3 else "pending"
            job.failure_reason = reason
            job.lease_token = job.lease_until = None

    def defer(self, claim: Claim, reason: str) -> None:
        """試行数を返し、DB時計で30秒後に再取得可能にする。失効時はLeaseLost。"""
        with self._transaction() as session:
            job = self._owned(session, claim)
            job.status = "pending"
            job.attempts -= 1
            job.available_at = session.scalar(select(func.clock_timestamp())) + timedelta(
                seconds=30
            )
            job.failure_reason = reason
            job.lease_token = job.lease_until = None

    def complete(
        self,
        claim: Claim,
        info: RunInfo,
        register: Callable[[Session, ProcessingRun], None],
        files: Sequence[tuple[Path, Path]] = (),
    ) -> uuid.UUID:
        """不変ファイルを公開し、所有権付き取引で参照・結果・成功を確定する。

        filesは(試行固有の一時ファイル, 出力名)。同じディレクトリで作成すること。
        実際の保存先は毎回新しい専用ディレクトリに置き、run.output_pathsへ保存する。
        registerは出力名からrun.output_pathsを引いて結果のファイル参照を登録する。
        registerは渡されたSessionでのみDB登録し、commitや外部副作用を行わない。
        DB失敗や所有権喪失では未参照ファイルが残りうる。既存ファイルは置換しない。
        成功済みの再呼出しは既存run IDを返す。
        """
        output_paths = {}
        try:
            with self._transaction() as session:
                job = session.get(Job, claim.id)
                if job.status == "succeeded":
                    return job.run_id
                if job.lease_token != claim.token:
                    raise LeaseLost("ジョブのリースを失いました")
                managed = job.asset_id is not None and session.scalar(select(
                    retention.Retention.id,
                ).where(retention.Retention.asset_id == job.asset_id)) is not None
                if managed:
                    retention.lock(session)
                    retention.assert_usable(session, job.asset_id, images=True)
                for temporary, target in files:
                    if temporary.parent != target.parent or temporary == target:
                        raise ValueError("一時ファイルは出力名と同じディレクトリに分離してください")
                    directory = target.parent / f".output-{claim.token}-{uuid.uuid4()}"
                    published = directory / target.name
                    output_paths[str(target)] = str(published)
                    if managed:
                        retention.register_file(
                            session, job.asset_id,
                            claim.payload.get("host", socket.gethostname()), published,
                            "mask" if job.stage == "segment" else "derived",
                        )
            with (self._transaction() if managed else nullcontext()) as session:
                if managed:
                    retention.lock(session)
                    retention.assert_usable(session, claim.asset_id, images=True)
                for temporary, target in files:
                    published = Path(output_paths[str(target)])
                    published.parent.mkdir(mode=0o700)
                    temporary.replace(published)
                    published.chmod(0o600)
            with self._transaction() as session:
                retention.lock(session)
                job = session.scalars(select(Job).where(Job.id == claim.id).with_for_update()).one()
                if job.status == "succeeded":
                    return job.run_id
                self._owned(session, claim)
                category = info.license_class
                if job.asset_id is not None:
                    retention.assert_usable(session, job.asset_id, images=True)
                    asset = session.get(Asset, job.asset_id)
                    source = session.get(Source, asset.source_id)
                    category = combine_license(category, asset.license_class, source.license_class)
                run = ProcessingRun(
                    stage=job.stage,
                    config_hash=job.stage_config_hash,
                    license_class=category,
                    code_version=info.code_version,
                    taxonomy_version=info.taxonomy_version,
                    node=info.node,
                    parameters=info.parameters,
                    output_paths=output_paths,
                    model_name=info.model_name,
                    weights_hash=info.weights_hash,
                    started_at=claim.started_at,
                )
                session.add(run)
                session.flush()
                register(session, run)
                run.finished_at = session.scalar(select(func.clock_timestamp()))
                job.run_id = run.id
                job.status = "succeeded"
                job.lease_token = job.lease_until = None
                return run.id
        except BaseException:
            if claim.stage == "collect":
                for path in output_paths.values():
                    Path(path).unlink(missing_ok=True)
            raise

    def check_input(self, claim: Claim) -> None:
        """子プロセスへ画像を渡す前に現在の保持・利用条件を確認する。"""
        with self._transaction() as session:
            if claim.asset_id is not None:
                retention.assert_usable(session, claim.asset_id, images=True)
                if claim.stage in {"color", "shade"}:
                    retention.check_privacy(session, claim.asset_id, claim.payload)
