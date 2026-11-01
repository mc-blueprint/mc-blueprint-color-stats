"""ジョブの取得・更新は短いトランザクション、結果登録は完了確定と同一取引。"""

import uuid
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from colorstats.schema.models import Job, ProcessingRun

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

    def claim(self, stages: Sequence[str]) -> Claim | None:
        """指定stageから1件取得する。期限切れも1失敗と数え、3試行で打ち切る。"""
        with self._transaction() as session:
            while True:
                job = session.scalars(
                    select(Job)
                    .where(
                        Job.stage.in_(stages),
                        or_(
                            Job.status == "pending",
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
            job.lease_until = session.scalar(select(func.clock_timestamp())) + self.lease

    def fail(self, claim: Claim, reason: str) -> None:
        """失敗理由を保存し、3試行未満はpendingへ戻す。期限切れはLeaseLost。"""
        with self._transaction() as session:
            job = self._owned(session, claim)
            job.status = "failed" if job.attempts >= 3 else "pending"
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
        with self._transaction() as session:
            job = session.get(Job, claim.id)
            if job.status == "succeeded":
                return job.run_id
            if job.lease_token != claim.token:
                raise LeaseLost("ジョブのリースを失いました")
        output_paths = {}
        for temporary, target in files:
            if temporary.parent != target.parent or temporary == target:
                raise ValueError("一時ファイルは出力名と同じディレクトリに分離してください")
            directory = target.parent / f".output-{claim.token}-{uuid.uuid4()}"
            directory.mkdir()
            published = directory / target.name
            temporary.replace(published)
            output_paths[str(target)] = str(published)
        with self._transaction() as session:
            job = session.scalars(select(Job).where(Job.id == claim.id).with_for_update()).one()
            if job.status == "succeeded":
                return job.run_id
            self._owned(session, claim)
            run = ProcessingRun(
                stage=job.stage,
                config_hash=job.stage_config_hash,
                license_class=info.license_class,
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
