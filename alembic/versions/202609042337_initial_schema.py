"""add mitre_technique_catalog table

Revision ID: 3d80e7dde786
Revises: 17d4213fc13f
Create Date: 2026-09-05

The FULL official MITRE ATT&CK Enterprise catalog -- NOT customer-
scoped, a single shared reference table synced periodically from
MITRE's own public STIX data (confirmed source:
github.com/mitre-attack/attack-stix-data). Used by MitreGapAnalyzer
to compare a customer's ACTUAL technique coverage (rule_mitre_unified)
against the full official framework, not just what's been observed.

IMPORTANT: verify down_revision matches your real `alembic heads`.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "202609081537"
down_revision = "202609042337"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mitre_technique_catalog",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("technique_id", sa.Text(), nullable=False),
        sa.Column("technique_name", sa.Text(), nullable=True),
        sa.Column("tactic_names", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("is_subtechnique", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("parent_technique_id", sa.Text(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_mitre_technique_catalog_technique_id", "mitre_technique_catalog", ["technique_id"])
    op.create_index("ix_mitre_technique_catalog_technique_id", "mitre_technique_catalog", ["technique_id"])


def downgrade() -> None:
    op.drop_index("ix_mitre_technique_catalog_technique_id", table_name="mitre_technique_catalog")
    op.drop_constraint("uq_mitre_technique_catalog_technique_id", "mitre_technique_catalog", type_="unique")
    op.drop_table("mitre_technique_catalog")