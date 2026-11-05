"""新規収集分だけを対象とする保持・削除台帳。既存画像は登録しない。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "retention_stop",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("details", JSONB(), nullable=False),
        sa.UniqueConstraint("provider", "source_url", "target_url"),
    )
    op.create_table(
        "retention",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("asset.id"), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True)),
        sa.Column("reason", sa.Text()),
        sa.Column("request_url", sa.Text()),
        sa.Column("backup_until", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "retention_file",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("retention.asset_id"), nullable=False),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.UniqueConstraint("asset_id", "host", "path"),
    )
    op.create_index(op.f("ix_retention_file_asset_id"), "retention_file", ["asset_id"])
    op.create_index(op.f("ix_retention_file_path"), "retention_file", ["path"])


def downgrade():
    op.execute("LOCK TABLE retention_stop, retention, retention_file IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM retention) OR EXISTS (SELECT 1 FROM retention_stop) THEN
                RAISE EXCEPTION '保持台帳が残るため巻戻しできません';
            END IF;
        END $$
    """)
    op.drop_table("retention_file")
    op.drop_table("retention")
    op.drop_table("retention_stop")
