"""リースと一意な結果確定を持つジョブ。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "processing_run",
        sa.Column("output_paths", postgresql.JSONB(), server_default="{}", nullable=False),
    )
    op.create_table(
        "job",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("stage_config_hash", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_job"),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"], name="fk_job_asset_id_asset"),
        sa.ForeignKeyConstraint(
            ["run_id"], ["processing_run.id"], name="fk_job_run_id_processing_run"
        ),
        sa.UniqueConstraint("run_id", name="uq_job_run_id"),
        sa.UniqueConstraint(
            "stage",
            "asset_id",
            "stage_config_hash",
            name="uq_job_key",
            postgresql_nulls_not_distinct=True,
        ),
        sa.CheckConstraint(
            "stage IN ('collect','prep','segment','shade','color','review','aggregate')",
            name="ck_job_stage",
        ),
        sa.CheckConstraint(
            "status IN ('pending','running','succeeded','failed')", name="ck_job_status"
        ),
        sa.CheckConstraint("attempts BETWEEN 0 AND 3", name="ck_job_attempts"),
        sa.CheckConstraint(
            "(status = 'running') = (lease_token IS NOT NULL AND lease_until IS NOT NULL)",
            name="ck_job_lease",
        ),
        sa.CheckConstraint("(status = 'succeeded') = (run_id IS NOT NULL)", name="ck_job_result"),
    )
    op.create_index("ix_job_poll", "job", ["stage", "status", "lease_until"])


def downgrade():
    op.drop_index("ix_job_poll", table_name="job")
    op.drop_table("job")
    op.drop_column("processing_run", "output_paths")
