

"""add log_sources_reference table

Revision ID: 17d4213fc13f
Revises: bf2b217b3247
Create Date: 2026-08-28

IMPORTANT: verify down_revision matches your real `alembic heads`.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "202609042337"
down_revision = "202608252333"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "log_sources_reference",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("qradar_log_source_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("type_id", sa.BigInteger(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("average_eps", sa.Float(), nullable=True),
        sa.Column("raw_json", postgresql.JSONB(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint(
        "uq_log_sources_reference_customer_qradar_id", "log_sources_reference", ["customer_id", "qradar_log_source_id"]
    )
    op.create_index("ix_log_sources_reference_customer_id", "log_sources_reference", ["customer_id"])
    op.create_index("ix_log_sources_reference_type_id", "log_sources_reference", ["type_id"])


def downgrade() -> None:
    op.drop_index("ix_log_sources_reference_type_id", table_name="log_sources_reference")
    op.drop_index("ix_log_sources_reference_customer_id", table_name="log_sources_reference")
    op.drop_constraint("uq_log_sources_reference_customer_qradar_id", "log_sources_reference", type_="unique")
    op.drop_table("log_sources_reference")