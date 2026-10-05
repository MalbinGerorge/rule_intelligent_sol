"""add embedded_at to rule_yaml_representations

Revision ID: 202609101455
Revises: 202609081537
Create Date: 2026-09-09
"""
import sqlalchemy as sa

from alembic import op

revision = "202609101455"
down_revision = "202609081537"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rule_yaml_representations", sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("rule_yaml_representations", "embedded_at")