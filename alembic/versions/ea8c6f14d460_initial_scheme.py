"""add is_builtin_field to custom_event_properties

Revision ID: 354ac644fcc5
Revises: ea8c6f14d460
Create Date: 2026-08-17

IMPORTANT: verify this down_revision matches your real `alembic heads`
output before applying.

CONFIRMED NECESSARY from real data: 116 of 1,814 synced expressions
(6.4%) had a regex_property_identifier that didn't match any row in
regex_properties. Every single one was expression_type='aql', and
every parent identifier was a QRadar internal facade name
(PACKETS_FROM_SERVER_FACADE, SOURCE_PROCESS_FACADE, etc.) with a real,
useful display name in its own "expression" field ("Packets Received",
"Process Name"). These are QRadar's BUILT-IN fields -- regex_properties
only ever lists CUSTOM properties, so built-ins were never going to
appear there. Rather than discard this real, useful mapping (built-in
fields are arguably used MORE often in real AQL queries than custom
ones), this column lets both live in the same table, clearly labeled.
"""
from alembic import op
import sqlalchemy as sa

revision = "354ac644fcc5"
down_revision = "ea8c6f14d460"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "custom_event_properties",
        sa.Column("is_builtin_field", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("custom_event_properties", "is_builtin_field")