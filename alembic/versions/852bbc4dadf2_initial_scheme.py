"""add custom_event_properties and custom_event_property_expressions

Revision ID: ea8c6f14d460
Revises: 0752f60bef66
Create Date: 2026-08-17

IMPORTANT: verify this down_revision matches your real `alembic heads`
output before applying -- sandbox and production Postgres instances
may have diverged.

Captures QRadar's custom event property definitions (regex_properties)
and their per-log-source-type extraction logic, across all 6 payload
formats (regex, JSON, XML, CEF, LEEF, NVP) plus AQL expressions.
Confirmed real field shapes from QRadar's own API documentation
(pasted directly by the user, not assumed).

Two tables, mirroring the parent/child relationship QRadar itself
uses: one property (e.g. "Command") can have a DIFFERENT extraction
expression per log source type, since different vendors format their
raw logs differently.

Refreshed via FULL DELETE-then-INSERT on every sync (not incremental
modification-date comparison) -- deliberate choice: not every
expression type's endpoint confirms a modification_date field, so
incremental comparison would be inconsistent across types. Full
refresh is simple, uniform, and correctly handles deletions on the
QRadar side too (which pure modification-date comparison alone would
never catch).
"""
from alembic import op
import sqlalchemy as sa

revision = "ea8c6f14d460"
down_revision = "852bbc4dadf2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "custom_event_properties",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("qradar_identifier", sa.Text(), nullable=False),  # QRadar's own UUID identifier
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("property_type", sa.Text(), nullable=True),  # STRING | NUMERIC | IP | PORT | TIME
        sa.Column("use_for_rule_engine", sa.Boolean(), nullable=True),
        sa.Column("datetime_format", sa.Text(), nullable=True),
        sa.Column("locale", sa.Text(), nullable=True),
        sa.Column("auto_discovered", sa.Boolean(), nullable=True),
        sa.Column("username", sa.Text(), nullable=True),  # owner in QRadar
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("customer_id", "qradar_identifier", name="uq_custom_event_properties_customer_identifier"),
    )
    op.create_index(
        "ix_custom_event_properties_customer_id", "custom_event_properties", ["customer_id"]
    )

    op.create_table(
        "custom_event_property_expressions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "property_id",
            sa.Integer(),
            sa.ForeignKey("custom_event_properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("qradar_identifier", sa.Text(), nullable=False),
        # regex | json | xml | cef | leef | nvp | aql -- which of the 6
        # expression endpoints (+ AQL) this row came from
        sa.Column("expression_type", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("log_source_type_id", sa.Integer(), nullable=True),
        sa.Column("log_source_id", sa.Integer(), nullable=True),
        sa.Column("qid", sa.Integer(), nullable=True),
        sa.Column("low_level_category_id", sa.Integer(), nullable=True),
        # Everything that varies by expression_type -- regex+capture_group+
        # format_string for the regex type, plain expression string for
        # json/xml/cef/leef/nvp/aql, delimiter_pair+delimiter_name_value
        # for nvp. Same "one flexible JSON column absorbs shape variation"
        # pattern as rule_conditions.structured_data.
        sa.Column("type_specific_data", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_custom_event_property_expressions_property_id",
        "custom_event_property_expressions",
        ["property_id"],
    )
    op.create_index(
        "ix_custom_event_property_expressions_log_source_type_id",
        "custom_event_property_expressions",
        ["log_source_type_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_custom_event_property_expressions_log_source_type_id", table_name="custom_event_property_expressions")
    op.drop_index("ix_custom_event_property_expressions_property_id", table_name="custom_event_property_expressions")
    op.drop_table("custom_event_property_expressions")
    op.drop_index("ix_custom_event_properties_customer_id", table_name="custom_event_properties")
    op.drop_table("custom_event_properties")