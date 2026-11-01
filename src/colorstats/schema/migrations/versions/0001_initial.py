"""分類・収集・解析・統計の初期スキーマ。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "processing_run",
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=True),
        sa.Column("weights_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "license_class",
            sa.Enum(
                "open",
                "noncommercial",
                "academic_only",
                "restricted",
                name="license_class",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("code_version", sa.Text(), nullable=False),
        sa.Column("taxonomy_version", sa.String(length=32), nullable=False),
        sa.Column("node", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name=op.f("ck_processing_run_time_order"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processing_run")),
    )
    op.create_table(
        "source",
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("site", sa.Text(), nullable=False),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("license", sa.Text(), nullable=False),
        sa.Column(
            "license_class",
            sa.Enum(
                "open",
                "noncommercial",
                "academic_only",
                "restricted",
                name="license_class",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("attribution", sa.Text(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("policy", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source")),
        sa.UniqueConstraint("url", name=op.f("uq_source_url")),
    )
    op.create_index(op.f("ix_source_site"), "source", ["site"], unique=False)
    op.create_table(
        "subject",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "domain",
            sa.Enum(
                "mc_vanilla",
                "mc_modded_or_shader",
                "mc_unknown",
                "real_building",
                "real_terrain",
                "text",
                name="domain",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("era", sa.Text(), nullable=True),
        sa.Column("taxonomy_version", sa.String(length=32), nullable=False),
        sa.Column("scene_attributes", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subject")),
    )
    op.create_table(
        "asset",
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        sa.Column("collected_title", sa.Text(), nullable=True),
        sa.Column("collected_location", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("phash", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column(
            "domain",
            sa.Enum(
                "mc_vanilla",
                "mc_modded_or_shader",
                "mc_unknown",
                "real_building",
                "real_terrain",
                "text",
                name="domain",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "license_class",
            sa.Enum(
                "open",
                "noncommercial",
                "academic_only",
                "restricted",
                name="license_class",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("search_provider", sa.Text(), nullable=True),
        sa.Column("search_query", sa.Text(), nullable=True),
        sa.Column(
            "search_parameters",
            postgresql.JSONB(none_as_null=True, astext_type=Text()),
            nullable=True,
        ),
        sa.Column("result_rank", sa.Integer(), nullable=True),
        sa.Column("result_page", sa.Integer(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("taxonomy_version", sa.String(length=32), nullable=False),
        sa.Column("scene_attributes", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("quality", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("result_page IS NULL OR result_page >= 0", name=op.f("ck_asset_page")),
        sa.CheckConstraint("result_rank IS NULL OR result_rank >= 0", name=op.f("ck_asset_rank")),
        sa.CheckConstraint("width > 0 AND height > 0", name=op.f("ck_asset_dimensions")),
        sa.ForeignKeyConstraint(
            ["source_id"], ["source.id"], name=op.f("fk_asset_source_id_source")
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subject.id"], name=op.f("fk_asset_subject_id_subject")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset")),
    )
    op.create_index(op.f("ix_asset_sha256"), "asset", ["sha256"], unique=False)
    op.create_index(op.f("ix_asset_source_id"), "asset", ["source_id"], unique=False)
    op.create_index(op.f("ix_asset_subject_id"), "asset", ["subject_id"], unique=False)
    op.create_table(
        "block_color",
        sa.Column("minecraft_version", sa.Text(), nullable=False),
        sa.Column("block_id", sa.Text(), nullable=False),
        sa.Column(
            "face",
            sa.Enum(
                "top",
                "side",
                "bottom",
                name="block_face",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("oklab", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("material_tags", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("processing_run_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["processing_run_id"],
            ["processing_run.id"],
            name=op.f("fk_block_color_processing_run_id_processing_run"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_block_color")),
        sa.UniqueConstraint(
            "minecraft_version",
            "block_id",
            "face",
            "processing_run_id",
            name=op.f("uq_block_color_minecraft_version"),
        ),
    )
    op.create_index(
        op.f("ix_block_color_processing_run_id"), "block_color", ["processing_run_id"], unique=False
    )
    op.create_table(
        "processing_run_input",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("input_run_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("run_id <> input_run_id", name=op.f("ck_processing_run_input_not_self")),
        sa.ForeignKeyConstraint(
            ["input_run_id"],
            ["processing_run.id"],
            name=op.f("fk_processing_run_input_input_run_id_processing_run"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["processing_run.id"],
            name=op.f("fk_processing_run_input_run_id_processing_run"),
        ),
        sa.PrimaryKeyConstraint("run_id", "input_run_id", name=op.f("pk_processing_run_input")),
    )
    op.create_table(
        "rule_stat",
        sa.Column("conditions", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("target_parts", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("distribution", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("subject_count", sa.Integer(), nullable=False),
        sa.Column("effective_sample_size", sa.Float(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("quality", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("confidence_interval", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("taxonomy_version", sa.String(length=32), nullable=False),
        sa.Column("processing_run_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "effective_sample_size >= 0 AND weight >= 0", name=op.f("ck_rule_stat_weights")
        ),
        sa.CheckConstraint(
            "sample_count >= 0 AND subject_count >= 0", name=op.f("ck_rule_stat_counts")
        ),
        sa.ForeignKeyConstraint(
            ["processing_run_id"],
            ["processing_run.id"],
            name=op.f("fk_rule_stat_processing_run_id_processing_run"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rule_stat")),
    )
    op.create_index(
        op.f("ix_rule_stat_processing_run_id"), "rule_stat", ["processing_run_id"], unique=False
    )
    op.create_table(
        "region",
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("processing_run_id", sa.Uuid(), nullable=False),
        sa.Column("taxonomy_version", sa.String(length=32), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("instance_id", sa.Text(), nullable=True),
        sa.Column("mask_path", sa.Text(), nullable=True),
        sa.Column("bbox", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("normalized_height", sa.Float(), nullable=True),
        sa.Column("orientation", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("terrain_attributes", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column(
            "label_source",
            sa.Enum(
                "model",
                "human",
                "vlm",
                "schematic",
                name="label_source",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("area_ratio", sa.Float(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("area_ratio BETWEEN 0 AND 1", name=op.f("ck_region_area_ratio")),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name=op.f("ck_region_confidence")),
        sa.CheckConstraint("normalized_height BETWEEN 0 AND 1", name=op.f("ck_region_height")),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"], name=op.f("fk_region_asset_id_asset")),
        sa.ForeignKeyConstraint(
            ["processing_run_id"],
            ["processing_run.id"],
            name=op.f("fk_region_processing_run_id_processing_run"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_region")),
        sa.UniqueConstraint("id", "asset_id", name=op.f("uq_region_id")),
    )
    op.create_index(op.f("ix_region_asset_id"), "region", ["asset_id"], unique=False)
    op.create_index(op.f("ix_region_label"), "region", ["label"], unique=False)
    op.create_index(
        op.f("ix_region_processing_run_id"), "region", ["processing_run_id"], unique=False
    )
    op.create_table(
        "subject_candidate",
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1", name=op.f("ck_subject_candidate_confidence")
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["asset.id"], name=op.f("fk_subject_candidate_asset_id_asset")
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subject.id"], name=op.f("fk_subject_candidate_subject_id_subject")
        ),
        sa.PrimaryKeyConstraint("asset_id", "subject_id", name=op.f("pk_subject_candidate")),
    )
    op.create_table(
        "color_observation",
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("region_id", sa.Uuid(), nullable=True),
        sa.Column("processing_run_id", sa.Uuid(), nullable=False),
        sa.Column("observed_oklab", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column(
            "material_oklab", postgresql.JSONB(none_as_null=True, astext_type=Text()), nullable=True
        ),
        sa.Column("material_confidence", sa.Float(), nullable=True),
        sa.Column("area_ratio", sa.Float(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(asset_id IS NULL) <> (region_id IS NULL)", name=op.f("ck_color_observation_target")
        ),
        sa.CheckConstraint(
            "(material_oklab IS NULL) = (material_confidence IS NULL)",
            name=op.f("ck_color_observation_material_pair"),
        ),
        sa.CheckConstraint(
            "area_ratio BETWEEN 0 AND 1", name=op.f("ck_color_observation_area_ratio")
        ),
        sa.CheckConstraint(
            "material_confidence BETWEEN 0 AND 1",
            name=op.f("ck_color_observation_material_confidence"),
        ),
        sa.ForeignKeyConstraint(
            ["processing_run_id"],
            ["processing_run.id"],
            name=op.f("fk_color_observation_processing_run_id_processing_run"),
        ),
        sa.ForeignKeyConstraint(
            ["region_id"], ["region.id"], name=op.f("fk_color_observation_region_id_region")
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["asset.id"], name=op.f("fk_color_observation_asset_id_asset")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_color_observation")),
    )
    op.create_index(
        op.f("ix_color_observation_asset_id"), "color_observation", ["asset_id"], unique=False
    )
    op.create_index(
        op.f("ix_color_observation_processing_run_id"),
        "color_observation",
        ["processing_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_color_observation_region_id"), "color_observation", ["region_id"], unique=False
    )
    op.create_table(
        "relation",
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("region_a", sa.Uuid(), nullable=False),
        sa.Column("region_b", sa.Uuid(), nullable=False),
        sa.Column("processing_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "adjacent",
                "contains",
                "above",
                "left_of",
                "co_occurs",
                name="relation_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("delta_l", sa.Float(), nullable=False),
        sa.Column("delta_c", sa.Float(), nullable=False),
        sa.Column("delta_h", sa.Float(), nullable=True),
        sa.Column("delta_e_ok", sa.Float(), nullable=False),
        sa.Column("area_ratio", sa.Float(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "delta_e_ok >= 0 AND area_ratio >= 0", name=op.f("ck_relation_nonnegative")
        ),
        sa.CheckConstraint("region_a <> region_b", name=op.f("ck_relation_different_regions")),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["asset.id"], name=op.f("fk_relation_asset_id_asset")
        ),
        sa.ForeignKeyConstraint(
            ["processing_run_id"],
            ["processing_run.id"],
            name=op.f("fk_relation_processing_run_id_processing_run"),
        ),
        sa.ForeignKeyConstraint(
            ["region_a", "asset_id"],
            ["region.id", "region.asset_id"],
            name=op.f("fk_relation_region_a_region"),
        ),
        sa.ForeignKeyConstraint(
            ["region_b", "asset_id"],
            ["region.id", "region.asset_id"],
            name=op.f("fk_relation_region_b_region"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_relation")),
        sa.UniqueConstraint(
            "region_a", "region_b", "type", "processing_run_id", name=op.f("uq_relation_region_a")
        ),
    )
    op.create_index(op.f("ix_relation_asset_id"), "relation", ["asset_id"], unique=False)
    op.create_index(
        op.f("ix_relation_processing_run_id"), "relation", ["processing_run_id"], unique=False
    )
    op.create_index(op.f("ix_relation_region_a"), "relation", ["region_a"], unique=False)
    op.create_index(op.f("ix_relation_region_b"), "relation", ["region_b"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_relation_region_b"), table_name="relation")
    op.drop_index(op.f("ix_relation_region_a"), table_name="relation")
    op.drop_index(op.f("ix_relation_processing_run_id"), table_name="relation")
    op.drop_index(op.f("ix_relation_asset_id"), table_name="relation")
    op.drop_table("relation")
    op.drop_index(op.f("ix_color_observation_region_id"), table_name="color_observation")
    op.drop_index(op.f("ix_color_observation_processing_run_id"), table_name="color_observation")
    op.drop_index(op.f("ix_color_observation_asset_id"), table_name="color_observation")
    op.drop_table("color_observation")
    op.drop_table("subject_candidate")
    op.drop_index(op.f("ix_region_processing_run_id"), table_name="region")
    op.drop_index(op.f("ix_region_label"), table_name="region")
    op.drop_index(op.f("ix_region_asset_id"), table_name="region")
    op.drop_table("region")
    op.drop_index(op.f("ix_rule_stat_processing_run_id"), table_name="rule_stat")
    op.drop_table("rule_stat")
    op.drop_table("processing_run_input")
    op.drop_index(op.f("ix_block_color_processing_run_id"), table_name="block_color")
    op.drop_table("block_color")
    op.drop_index(op.f("ix_asset_subject_id"), table_name="asset")
    op.drop_index(op.f("ix_asset_source_id"), table_name="asset")
    op.drop_index(op.f("ix_asset_sha256"), table_name="asset")
    op.drop_table("asset")
    op.drop_table("subject")
    op.drop_index(op.f("ix_source_site"), table_name="source")
    op.drop_table("source")
    op.drop_table("processing_run")
