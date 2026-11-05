"""providerリースと実配信先の通信予約を共有する。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "collection_limit",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("state", JSONB(), nullable=False),
    )


def downgrade():
    op.execute("LOCK TABLE collection_limit IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM collection_limit) THEN
                RAISE EXCEPTION '通信枠台帳が残るため巻戻しできません';
            END IF;
        END $$;
    """)
    op.drop_table("collection_limit")
