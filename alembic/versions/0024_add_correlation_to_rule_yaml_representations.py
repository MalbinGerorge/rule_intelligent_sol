"""add correlation support to rule_yaml_representations

Revision ID: 202608241719
Revises: 202608211535
Create Date: 2026-08-22

CONFIRMED against real Sigma spec (sigmahq.io/docs/meta/correlations.html):
threshold/count-based rules (ThresholdFunction_Test, TriggerMatchCount,
SequenceFunction_Test, DoubleSequenceFunction_Test, CauseAndEffect_Test,
TriggerTimeout -- 94 of 742 real rules, ~13%) are NOT expressible as a
single Sigma detection block. Real Sigma requires TWO separate linked
documents: a "base" detection rule (given a `name`) and a `correlation`
rule referencing it by that name.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202608241719"
down_revision = "202608211535"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rule_yaml_representations",
        sa.Column("role", sa.Text(), nullable=False, server_default="standalone"),
    )
    op.add_column(
        "rule_yaml_representations", sa.Column("rule_reference_name", sa.Text(), nullable=True)
    )
    op.add_column(
        "rule_yaml_representations", sa.Column("correlation", postgresql.JSONB(), nullable=True)
    )
    op.create_index("ix_rule_yaml_representations_role", "rule_yaml_representations", ["role"])


def downgrade() -> None:
    op.drop_index("ix_rule_yaml_representations_role", table_name="rule_yaml_representations")
    op.drop_column("rule_yaml_representations", "correlation")
    op.drop_column("rule_yaml_representations", "rule_reference_name")
    op.drop_column("rule_yaml_representations", "role")
