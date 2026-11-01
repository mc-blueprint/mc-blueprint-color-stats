"""subjectと独立した重複関係を保存する。既存の同定値は変更しない。"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "asset_duplicate",
        sa.Column("asset_a", sa.Uuid(), nullable=False),
        sa.Column("asset_b", sa.Uuid(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("asset_a", "asset_b", name="pk_asset_duplicate"),
        sa.ForeignKeyConstraint(["asset_a"], ["asset.id"], name="fk_asset_duplicate_asset_a_asset"),
        sa.ForeignKeyConstraint(["asset_b"], ["asset.id"], name="fk_asset_duplicate_asset_b_asset"),
        sa.CheckConstraint("asset_a < asset_b", name="ck_asset_duplicate_ordered_assets"),
        sa.CheckConstraint("method IN ('sha256', 'phash')", name="ck_asset_duplicate_method"),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_asset_duplicate_confidence"),
    )


def downgrade():
    op.drop_table("asset_duplicate")
