"""収集の集中枠をリースと結び付ける。"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "collection_reservation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("lease_token", sa.Uuid(), nullable=False),
        sa.Column("stratum", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), nullable=True),
        sa.Column("region_basis", sa.Text(), nullable=False),
        sa.Column("attributes", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_collection_reservation"),
        sa.ForeignKeyConstraint(
            ["job_id"], ["job.id"], name="fk_collection_reservation_job_id_job"
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subject.id"], name="fk_collection_reservation_subject_id_subject"
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["asset.id"], name="fk_collection_reservation_asset_id_asset"
        ),
        sa.UniqueConstraint("asset_id", name="uq_collection_reservation_asset_id"),
        sa.UniqueConstraint(
            "job_id", "lease_token", "source_url", name="uq_collection_reservation_job_id"
        ),
    )
    op.create_index("ix_collection_reservation_job_id", "collection_reservation", ["job_id"])
    op.create_index("ix_collection_reservation_stratum", "collection_reservation", ["stratum"])


def downgrade():
    op.drop_index("ix_collection_reservation_stratum", table_name="collection_reservation")
    op.drop_index("ix_collection_reservation_job_id", table_name="collection_reservation")
    op.drop_table("collection_reservation")
