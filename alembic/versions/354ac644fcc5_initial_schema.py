"""add investigation_reports table

Revision ID: 3487bfa37cbd
Revises: 354ac644fcc5
Create Date: 2026-08-19

A real, persistent history of investigation runs -- not a cache the
system reads to skip fresh work (reference set contents, log source
status, and AQL results all stay deliberately LIVE-only, per earlier
decisions this session), but an archive for later review: building
the golden test set, tuning prompts against real past runs, browsing
history for a given rule over time.

final_report is JSONB (the structured FinalReport object), not just
the rendered text -- lets you later query things like "every
investigation where a root cause had confidence=high", same reasoning
as rule_conditions.structured_data throughout this project.

No UNIQUE constraint on (customer_id, rule_id) -- deliberate: multiple
rows per rule over time are the whole point, a real history, not a
single overwritten snapshot.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "3487bfa37cbd"
down_revision = "354ac644fcc5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "investigation_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chain_analysis", postgresql.JSONB(), nullable=True),
        sa.Column("final_report", postgresql.JSONB(), nullable=True),
        sa.Column("rendered_report", sa.Text(), nullable=True),
        sa.Column("trace", sa.Text(), nullable=True),
        sa.Column("tool_calls_made", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_investigation_reports_customer_id", "investigation_reports", ["customer_id"])
    op.create_index("ix_investigation_reports_rule_id", "investigation_reports", ["rule_id"])
    op.create_index("ix_investigation_reports_created_at", "investigation_reports", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_investigation_reports_created_at", table_name="investigation_reports")
    op.drop_index("ix_investigation_reports_rule_id", table_name="investigation_reports")
    op.drop_index("ix_investigation_reports_customer_id", table_name="investigation_reports")
    op.drop_table("investigation_reports")