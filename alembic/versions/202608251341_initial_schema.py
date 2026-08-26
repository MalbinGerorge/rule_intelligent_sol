"""add rule_mitre_unified table

Revision ID: bf2b217b3247
Revises: 3d7ed659fb78
Create Date: 2026-08-25

A REAL table (not a view), so it appears normally in database
browsers -- must be refreshed explicitly via
sync_rule_mitre_unified() after anything changes rule_summary's
MITRE data or rule_yaml_representations.mitre_techniques_inferred.

CONFIRMED CORRECT SOURCE, from real data: confirmed MITRE mappings
must be read from mitre_mappings directly, NOT from
rule_summary.tactics/techniques/sub_techniques (three independently-
aggregated arrays). Real data on rule 393 ("Chained Exploit...")
proved these arrays can have DIFFERENT LENGTHS -- some tactics were
enabled with zero techniques mapped under them -- so pairing them
positionally would silently produce fabricated, incorrect
tactic-technique associations. mitre_mappings preserves each real
tactic/technique/technique_name triplet exactly as QRadar recorded it.

If this table was previously created ad-hoc (e.g. directly in
Adminer, before this migration existed), the DROP TABLE IF EXISTS
below cleans that up so this migration becomes the single source of
truth for its schema going forward.
"""
from alembic import op
import sqlalchemy as sa

revision = "202608252333"
down_revision = "202608251341"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rule_mitre_unified")

    op.create_table(
        "rule_mitre_unified",
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("tactic", sa.Text(), nullable=True),
        sa.Column("technique_id", sa.Text(), nullable=True),
        sa.Column("technique_name", sa.Text(), nullable=True),
        sa.Column("mitre_source", sa.Text(), nullable=False),  # 'confirmed' | 'derived'
        sa.Column("confidence", sa.Text(), nullable=True),  # only set for 'derived' rows
    )
    op.create_index("ix_rule_mitre_unified_customer", "rule_mitre_unified", ["customer_id"])
    op.create_index("ix_rule_mitre_unified_technique", "rule_mitre_unified", ["technique_id"])


def downgrade() -> None:
    op.drop_index("ix_rule_mitre_unified_technique", table_name="rule_mitre_unified")
    op.drop_index("ix_rule_mitre_unified_customer", table_name="rule_mitre_unified")
    op.drop_table("rule_mitre_unified")