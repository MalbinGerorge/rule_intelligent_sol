"""add rule_yaml_representations table

Revision ID: 51b5e16468e4
Revises: 3487bfa37cbd
Create Date: 2026-08-21

Stores the LLM-generated Sigma-format representation of each rule
(including its inlined building block chain), plus MITRE mapping that
the LLM infers when no official QRadar mapping exists.

CRITICAL distinction, deliberately enforced by keeping this in a
SEPARATE table from the existing mitre_mappings: LLM-inferred
techniques are a genuinely lower-confidence signal than QRadar's own
vendor-curated mapping. They must never be silently merged with
confirmed data -- mitre_techniques_inferred here is explicitly a
different, labeled source, never written into mitre_mappings itself.

Structured columns mirror the REAL Sigma specification fields
(confirmed against SigmaHQ's own spec, not invented): title,
description, status, level, logsource (category/product/service),
detection (selections + condition), tags, falsepositives, references.
Kept as separate typed/JSONB columns (not one blob of YAML text) so
they're directly queryable -- e.g. filtering by level or log source
product without parsing YAML on every read. The portable YAML text
itself is rendered on demand (Jinja, same pattern as report_renderer.py),
not stored redundantly.

embedding is pgvector, dimension 384 -- matches
sentence-transformers/all-MiniLM-L6-v2, chosen deliberately to run
LOCALLY (no rule content ever transmitted externally for embedding),
an extra layer of protection on top of the de-identification the LLM
performs when generating the Sigma representation itself.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

revision = "202608211535"
down_revision = "202608201644"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "rule_yaml_representations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),

        # -- Real Sigma spec fields (confirmed against SigmaHQ) --
        sa.Column("sigma_id", sa.Text(), nullable=False),  # UUID v4, generated at creation
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="experimental"),
        sa.Column("level", sa.Text(), nullable=True),  # informational|low|medium|high|critical
        sa.Column("logsource", postgresql.JSONB(), nullable=True),  # {category, product, service}
        sa.Column("detection", postgresql.JSONB(), nullable=False),  # {selections: {...}, condition: "..."}
        sa.Column("tags", postgresql.JSONB(), nullable=True),  # ["attack.t1110", "attack.credential_access", ...]
        sa.Column("falsepositives", postgresql.JSONB(), nullable=True),
        sa.Column("references", postgresql.JSONB(), nullable=True),

        # -- Our own additions, kept explicitly separate from Sigma's own fields --
        sa.Column("mitre_techniques_inferred", postgresql.JSONB(), nullable=True),
        # each entry: {"technique_id": "T1110", "technique_name": "...", "confidence": "high|medium|low"}
        # NEVER merged into the existing mitre_mappings table -- see module docstring.

        sa.Column("embedding", Vector(384), nullable=True),  # populated in a separate pass, after generation

        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_index("ix_rule_yaml_representations_rule_id", "rule_yaml_representations", ["rule_id"])
    op.create_index("ix_rule_yaml_representations_customer_id", "rule_yaml_representations", ["customer_id"])
    # ivfflat index deliberately NOT created yet -- needs a meaningful
    # amount of real data to be effective; add once volume justifies it.


def downgrade() -> None:
    op.drop_index("ix_rule_yaml_representations_customer_id", table_name="rule_yaml_representations")
    op.drop_index("ix_rule_yaml_representations_rule_id", table_name="rule_yaml_representations")
    op.drop_table("rule_yaml_representations")