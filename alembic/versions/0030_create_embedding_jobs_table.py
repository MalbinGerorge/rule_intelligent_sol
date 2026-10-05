"""add embedding_jobs table

Revision ID: 202609101500
Revises: 202609101455
Create Date: 2026-09-09
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202609101500"
down_revision = "202609101455"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "embedding_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="running"),
        sa.Column("total_representations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_representations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_representations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_details", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_embedding_jobs_status", "embedding_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_embedding_jobs_status", table_name="embedding_jobs")
    op.drop_table("embedding_jobs")