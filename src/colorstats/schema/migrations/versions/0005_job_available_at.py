"""保存先の復旧を待つジョブの再取得時刻を保存する。"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "job",
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )


def downgrade():
    op.drop_column("job", "available_at")
