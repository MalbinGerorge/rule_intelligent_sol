"""add sigma_generation_jobs table

Revision ID: 3d7ed659fb78
Revises: 8fdae31c2e69
Create Date: 2026-08-23

Tracks async batch Sigma-generation runs -- one row per "generate
Sigma for customer X" request, whether for all rules or a specific
named list. Same async-job pattern as investigation_reports: created
immediately (status='running') so the caller has an id to poll,
updated in place as processing continues, always reaches a terminal
status even on failure.

processed_rules/failed_rules update INCREMENTALLY during the run (not
just at the end) so polling shows live progress on a run that could
take a long time (700+ rules, one LLM call each).

IMPORTANT: verify down_revision matches your real `alembic heads`.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "202608251341"
down_revision = "202608241719"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sigma_generation_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="running"),
        sa.Column("requested_rule_names", postgresql.JSONB(), nullable=True),  # NULL = all canonical rules
        sa.Column("total_rules", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_rules", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_rules", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_rule_details", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sigma_generation_jobs_customer_id", "sigma_generation_jobs", ["customer_id"])
    op.create_index("ix_sigma_generation_jobs_status", "sigma_generation_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_sigma_generation_jobs_status", table_name="sigma_generation_jobs")
    op.drop_index("ix_sigma_generation_jobs_customer_id", table_name="sigma_generation_jobs")
    op.drop_table("sigma_generation_jobs")