"""add primary key to rule_mitre_unified

Revision ID: d0f94b82467c
Revises: 75870c08f395
Create Date: 2026-09-11

CONFIRMED REAL GAP: the original migration for this table never
defined a primary key at all. Every SQLAlchemy ORM model requires
one -- discovered while building proper model classes for all tables
created via hand-written migrations so far (they were never added to
app/models/, a real risk given target_metadata = Base.metadata and
autogenerate now being available: Alembic could otherwise see these
as unwanted tables and generate a DROP for them).

IMPORTANT: verify down_revision matches your real `alembic heads`.
"""
from alembic import op
import sqlalchemy as sa

revision = "202609111828"
down_revision = "202609101500"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rule_mitre_unified",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), primary_key=True),
    )


def downgrade() -> None:
    op.drop_column("rule_mitre_unified", "id")