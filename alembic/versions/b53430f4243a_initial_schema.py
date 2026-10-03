"""add rule_responses table -- offense/event-dispatch and reference-write actions

Revision ID: 852bbc4dadf2
Revises: b53430f4243a
Create Date: 2026-08-16

Captures the <responses>/<limiter> section of rule_xml -- a
DIFFERENT part of the tree from <testDefinitions> (conditions).
Confirmed real shapes from actual Cotecna data:
  - <newevent>: offense creation/naming behavior, event dispatch
    metadata. forceOffenseCreation confirmed via real data as a
    genuinely common reason a structurally-correct rule produces no
    visible offense (107 of 740 event-dispatching rules have it false).
  - <referenceDataResponse>: this rule WRITES to a reference
    set/map/table -- the OPPOSITE direction from ReferenceSetTest/
    ReferenceDataTest (which READ from one). Confirmed rare (4 of 1152
    real rules) but real.
  - <limiter> (sibling of <responses>, not nested inside it):
    response deduplication/throttling -- confirmed relevant from the
    real Fortigate rule pulled earlier in this project.

offense_mapping stored as a RAW, UNRESOLVED integer. Confirmed from
real data this is NOT a small fixed platform enum (61 distinct values
observed, several >100) -- almost certainly an index into a
customer-specific list mixing built-in identity fields with that
customer's own Custom Event Properties. Resolving it needs ingesting
each customer's Custom Event Property list (a separate, later piece
of work) -- stored as a bare number for now so nothing is lost.
"""
from alembic import op
import sqlalchemy as sa

revision = "852bbc4dadf2"
down_revision = "b53430f4243a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rule_responses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("rules.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("event_name", sa.Text(), nullable=True),
        sa.Column("event_description", sa.Text(), nullable=True),
        sa.Column("severity", sa.Integer(), nullable=True),
        sa.Column("credibility", sa.Integer(), nullable=True),
        sa.Column("relevance", sa.Integer(), nullable=True),
        sa.Column("qid", sa.Integer(), nullable=True),
        sa.Column("low_level_category", sa.Integer(), nullable=True),
        sa.Column("force_offense_creation", sa.Boolean(), nullable=True),
        sa.Column("describe_offense", sa.Boolean(), nullable=True),
        sa.Column("override_offense_name", sa.Boolean(), nullable=True),
        sa.Column("contribute_offense_name", sa.Boolean(), nullable=True),
        sa.Column("offense_mapping", sa.Integer(), nullable=True),
        sa.Column("ref_write_target_name", sa.Text(), nullable=True),
        sa.Column("ref_write_key_field", sa.Text(), nullable=True),
        sa.Column("ref_write_filter", sa.Text(), nullable=True),
        sa.Column("ref_write_type", sa.Text(), nullable=True),
        sa.Column("limiter_response_count", sa.Integer(), nullable=True),
        sa.Column("limiter_interval_count", sa.Integer(), nullable=True),
        sa.Column("limiter_interval_type", sa.Text(), nullable=True),
        sa.Column("limiter_host_type", sa.Text(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_rule_responses_rule_id", "rule_responses", ["rule_id"])


def downgrade() -> None:
    op.drop_index("ix_rule_responses_rule_id", table_name="rule_responses")
    op.drop_table("rule_responses")