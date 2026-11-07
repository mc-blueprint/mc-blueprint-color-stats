"""画像判定APIの共有予算と送信台帳。金額は整数nano USD。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "api_budget",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("cap_nusd", sa.BigInteger(), nullable=False),
        sa.Column("pricing", JSONB(), nullable=False),
        sa.Column("stopped", sa.Boolean(), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.CheckConstraint("cap_nusd > 0", name=op.f("ck_api_budget_cap")),
    )
    op.create_table(
        "api_call",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("budget_key", sa.Text(), sa.ForeignKey("api_budget.key"), nullable=False),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("job.id"), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("reserved_nusd", sa.BigInteger(), nullable=False),
        sa.Column("cost_nusd", sa.BigInteger()),
        sa.Column("response_path", sa.Text(), nullable=False),
        sa.Column("response_hash", sa.String(64)),
        sa.Column("details", JSONB(), nullable=False),
        sa.UniqueConstraint("job_id", "endpoint", "attempt", name="uq_api_call_job_id"),
        sa.CheckConstraint("reserved_nusd >= 0 AND (cost_nusd IS NULL OR cost_nusd >= 0)",
                           name=op.f("ck_api_call_amount")),
        sa.CheckConstraint("attempt BETWEEN 1 AND 3", name=op.f("ck_api_call_attempt")),
        sa.CheckConstraint("state IN ('sent','settled','unknown','retry','stopped')",
                           name=op.f("ck_api_call_state")),
    )
    for column in ("budget_key", "job_id", "input_hash"):
        op.create_index(f"ix_api_call_{column}", "api_call", [column])


def downgrade():
    op.execute("LOCK TABLE api_call IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM api_call) THEN
                RAISE EXCEPTION 'API送信台帳が残るため巻戻しできません';
            END IF;
        END $$;
    """)
    op.drop_table("api_call")
    op.drop_table("api_budget")
