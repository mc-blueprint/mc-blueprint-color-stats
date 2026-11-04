"""解析専用区分を全VARCHAR/CHECKへ追加する。既存行は変更しない。"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

TABLES = ("source", "asset", "processing_run")
PREVIOUS = "'open', 'noncommercial', 'academic_only', 'restricted'"


def upgrade():
    for table in TABLES:
        op.drop_constraint(op.f(f"ck_{table}_license_class"), table, type_="check")
        op.create_check_constraint(
            op.f(f"ck_{table}_license_class"), table,
            f"license_class IN ({PREVIOUS}, 'analysis_only')",
        )


def downgrade():
    # ロック中に確認し、検査後の同時挿入でも部分的な巻戻しにならないようにする。
    op.execute("LOCK TABLE source, asset, processing_run IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM source WHERE license_class = 'analysis_only')
            OR EXISTS (SELECT 1 FROM asset WHERE license_class = 'analysis_only')
            OR EXISTS (SELECT 1 FROM processing_run WHERE license_class = 'analysis_only')
            THEN RAISE EXCEPTION 'analysis_only行が残るため巻戻しできません';
            END IF;
        END $$
    """)
    for table in TABLES:
        op.drop_constraint(op.f(f"ck_{table}_license_class"), table, type_="check")
        op.create_check_constraint(
            op.f(f"ck_{table}_license_class"), table, f"license_class IN ({PREVIOUS})",
        )
