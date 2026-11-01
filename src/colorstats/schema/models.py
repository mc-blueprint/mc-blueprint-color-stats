"""解析の由来を保持するPostgreSQL 16向けモデル。列の意味はdocs/schema.mdを参照。"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

LICENSE_CLASS = Enum(
    "open",
    "noncommercial",
    "academic_only",
    "restricted",
    name="license_class",
    native_enum=False,
    create_constraint=True,
)
DOMAIN = Enum(
    "mc_vanilla",
    "mc_modded_or_shader",
    "mc_unknown",
    "real_building",
    "real_terrain",
    "text",
    name="domain",
    native_enum=False,
    create_constraint=True,
)


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class Identity:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class Source(Identity, Base):
    __tablename__ = "source"

    url: Mapped[str] = mapped_column(Text, unique=True)
    site: Mapped[str] = mapped_column(Text, index=True)
    author: Mapped[str | None] = mapped_column(Text)
    license: Mapped[str] = mapped_column(Text)
    license_class: Mapped[str] = mapped_column(LICENSE_CLASS)
    attribution: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    policy: Mapped[dict] = mapped_column(JSONB)


class Subject(Identity, Base):
    __tablename__ = "subject"

    name: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(DOMAIN)
    location: Mapped[str | None] = mapped_column(Text)
    era: Mapped[str | None] = mapped_column(Text)
    taxonomy_version: Mapped[str] = mapped_column(String(32))
    scene_attributes: Mapped[dict] = mapped_column(JSONB)


class Asset(Identity, Base):
    __tablename__ = "asset"
    __table_args__ = (
        CheckConstraint("width > 0 AND height > 0", name="dimensions"),
        CheckConstraint("result_rank IS NULL OR result_rank >= 0", name="rank"),
        CheckConstraint("result_page IS NULL OR result_page >= 0", name="page"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source.id"), index=True)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("subject.id"), index=True)
    collected_title: Mapped[str | None] = mapped_column(Text)
    collected_location: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    phash: Mapped[str | None] = mapped_column(Text)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(DOMAIN)
    license_class: Mapped[str] = mapped_column(LICENSE_CLASS)
    search_provider: Mapped[str | None] = mapped_column(Text)
    search_query: Mapped[str | None] = mapped_column(Text)
    search_parameters: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    result_rank: Mapped[int | None] = mapped_column(Integer)
    result_page: Mapped[int | None] = mapped_column(Integer)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    taxonomy_version: Mapped[str] = mapped_column(String(32))
    scene_attributes: Mapped[dict] = mapped_column(JSONB)
    quality: Mapped[dict] = mapped_column(JSONB)


class SubjectCandidate(Base):
    __tablename__ = "subject_candidate"
    __table_args__ = (CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence"),)

    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("asset.id"), primary_key=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subject.id"), primary_key=True)
    confidence: Mapped[float] = mapped_column(Float)
    evidence: Mapped[dict] = mapped_column(JSONB)


class ProcessingRun(Identity, Base):
    __tablename__ = "processing_run"
    __table_args__ = (
        CheckConstraint("finished_at IS NULL OR finished_at >= started_at", name="time_order"),
    )

    stage: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str | None] = mapped_column(Text)
    weights_hash: Mapped[str | None] = mapped_column(String(64))
    license_class: Mapped[str] = mapped_column(LICENSE_CLASS)
    config_hash: Mapped[str] = mapped_column(String(64))
    parameters: Mapped[dict] = mapped_column(JSONB)
    output_paths: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    code_version: Mapped[str] = mapped_column(Text)
    taxonomy_version: Mapped[str] = mapped_column(String(32))
    node: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)


class Job(Identity, Base):
    __tablename__ = "job"
    __table_args__ = (
        UniqueConstraint(
            "stage",
            "asset_id",
            "stage_config_hash",
            name="uq_job_key",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "stage IN ('collect','prep','segment','shade','color','review','aggregate')",
            name="stage",
        ),
        CheckConstraint("status IN ('pending','running','succeeded','failed')", name="status"),
        CheckConstraint("attempts BETWEEN 0 AND 3", name="attempts"),
        CheckConstraint(
            "(status = 'running') = (lease_token IS NOT NULL AND lease_until IS NOT NULL)",
            name="lease",
        ),
        CheckConstraint("(status = 'succeeded') = (run_id IS NOT NULL)", name="result"),
        Index("ix_job_poll", "stage", "status", "lease_until"),
    )

    stage: Mapped[str] = mapped_column(Text)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("asset.id"))
    stage_config_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("processing_run.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CollectionReservation(Identity, Base):
    __tablename__ = "collection_reservation"
    __table_args__ = (UniqueConstraint("job_id", "lease_token", "source_url"),)

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job.id"), index=True)
    lease_token: Mapped[uuid.UUID] = mapped_column(Uuid)
    stratum: Mapped[str] = mapped_column(Text, index=True)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("subject.id"))
    author: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    region_basis: Mapped[str] = mapped_column(Text)
    attributes: Mapped[dict] = mapped_column(JSONB)
    source_url: Mapped[str] = mapped_column(Text)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("asset.id"), unique=True)


class ProcessingRunInput(Base):
    __tablename__ = "processing_run_input"
    __table_args__ = (CheckConstraint("run_id <> input_run_id", name="not_self"),)

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("processing_run.id"), primary_key=True)
    input_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processing_run.id"), primary_key=True
    )


class Region(Identity, Base):
    __tablename__ = "region"
    __table_args__ = (
        UniqueConstraint("id", "asset_id"),
        CheckConstraint("area_ratio BETWEEN 0 AND 1", name="area_ratio"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence"),
        CheckConstraint("normalized_height BETWEEN 0 AND 1", name="height"),
    )

    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("asset.id"), index=True)
    processing_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processing_run.id"), index=True
    )
    taxonomy_version: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(Text, index=True)
    instance_id: Mapped[str | None] = mapped_column(Text)
    mask_path: Mapped[str | None] = mapped_column(Text)
    bbox: Mapped[list] = mapped_column(JSONB)
    normalized_height: Mapped[float | None] = mapped_column(Float)
    orientation: Mapped[dict | None] = mapped_column(JSONB)
    terrain_attributes: Mapped[dict | None] = mapped_column(JSONB)
    label_source: Mapped[str] = mapped_column(
        Enum(
            "model",
            "human",
            "vlm",
            "schematic",
            name="label_source",
            native_enum=False,
            create_constraint=True,
        )
    )
    confidence: Mapped[float] = mapped_column(Float)
    area_ratio: Mapped[float] = mapped_column(Float)


class ColorObservation(Identity, Base):
    __tablename__ = "color_observation"
    __table_args__ = (
        CheckConstraint("(asset_id IS NULL) <> (region_id IS NULL)", name="target"),
        CheckConstraint("area_ratio BETWEEN 0 AND 1", name="area_ratio"),
        CheckConstraint("material_confidence BETWEEN 0 AND 1", name="material_confidence"),
        CheckConstraint(
            "(material_oklab IS NULL) = (material_confidence IS NULL)", name="material_pair"
        ),
    )

    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("asset.id"), index=True)
    region_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("region.id"), index=True)
    processing_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processing_run.id"), index=True
    )
    observed_oklab: Mapped[dict] = mapped_column(JSONB)
    material_oklab: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    material_confidence: Mapped[float | None] = mapped_column(Float)
    area_ratio: Mapped[float] = mapped_column(Float)


class Relation(Identity, Base):
    __tablename__ = "relation"
    __table_args__ = (
        UniqueConstraint("region_a", "region_b", "type", "processing_run_id"),
        ForeignKeyConstraint(["region_a", "asset_id"], ["region.id", "region.asset_id"]),
        ForeignKeyConstraint(["region_b", "asset_id"], ["region.id", "region.asset_id"]),
        CheckConstraint("region_a <> region_b", name="different_regions"),
        CheckConstraint("delta_e_ok >= 0 AND area_ratio >= 0", name="nonnegative"),
    )

    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("asset.id"), index=True)
    region_a: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    region_b: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    processing_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processing_run.id"), index=True
    )
    type: Mapped[str] = mapped_column(
        Enum(
            "adjacent",
            "contains",
            "above",
            "left_of",
            "co_occurs",
            name="relation_type",
            native_enum=False,
            create_constraint=True,
        )
    )
    delta_l: Mapped[float] = mapped_column(Float)
    delta_c: Mapped[float] = mapped_column(Float)
    delta_h: Mapped[float | None] = mapped_column(Float)
    delta_e_ok: Mapped[float] = mapped_column(Float)
    area_ratio: Mapped[float] = mapped_column(Float)


class BlockColor(Identity, Base):
    __tablename__ = "block_color"
    __table_args__ = (
        UniqueConstraint("minecraft_version", "block_id", "face", "processing_run_id"),
    )

    minecraft_version: Mapped[str] = mapped_column(Text)
    block_id: Mapped[str] = mapped_column(Text)
    face: Mapped[str] = mapped_column(
        Enum(
            "top",
            "side",
            "bottom",
            name="block_face",
            native_enum=False,
            create_constraint=True,
        )
    )
    oklab: Mapped[dict] = mapped_column(JSONB)
    material_tags: Mapped[list] = mapped_column(JSONB)
    processing_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processing_run.id"), index=True
    )


class RuleStat(Identity, Base):
    __tablename__ = "rule_stat"
    __table_args__ = (
        CheckConstraint("sample_count >= 0 AND subject_count >= 0", name="counts"),
        CheckConstraint("effective_sample_size >= 0 AND weight >= 0", name="weights"),
    )

    conditions: Mapped[dict] = mapped_column(JSONB)
    target_parts: Mapped[list] = mapped_column(JSONB)
    distribution: Mapped[dict] = mapped_column(JSONB)
    sample_count: Mapped[int] = mapped_column(Integer)
    subject_count: Mapped[int] = mapped_column(Integer)
    effective_sample_size: Mapped[float] = mapped_column(Float)
    weight: Mapped[float] = mapped_column(Float)
    quality: Mapped[dict] = mapped_column(JSONB)
    confidence_interval: Mapped[dict | None] = mapped_column(JSONB)
    taxonomy_version: Mapped[str] = mapped_column(String(32))
    processing_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processing_run.id"), index=True
    )
