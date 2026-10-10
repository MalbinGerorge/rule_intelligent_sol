"""catalog keeps revoked techniques and MITRE tactics

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-10

Phase 2c-1 of the database redesign (docs/database/design.md).

QRadar maps rules to MITRE technique IDs that ATT&CK has since revoked and
replaced (e.g. T1562 -> T1685 in v19); the catalog kept only active
techniques, so those mappings pointed at nothing. The catalog now records
every technique MITRE publishes:

- status IN ('active', 'deprecated', 'revoked')
- replaced_by_technique_id -> the technique MITRE replaced a revoked one
  with (self foreign key; only revoked techniques have one)
- CHECKs: technique ID format; is_subtechnique iff a parent is set

mitre_tactics holds MITRE's own tactic IDs, names and STIX short names
(e.g. TA0005 "Stealth"), so tactic names come from MITRE's data instead of
a hard-coded mapping.

Existing rows are all active, so they default to status 'active'. Readers
of the catalog filter on status = 'active' in the same release; the
revoked rows are added by the next catalog sync.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CATALOG = "mitre_technique_catalog"


def upgrade() -> None:
    op.add_column(CATALOG, sa.Column("status", sa.Text(), nullable=False, server_default="active"))
    op.add_column(CATALOG, sa.Column("replaced_by_technique_id", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_mitre_technique_catalog_status",
        CATALOG,
        "status IN ('active', 'deprecated', 'revoked')",
    )
    op.create_check_constraint(
        "ck_mitre_technique_catalog_replaced_only_if_revoked",
        CATALOG,
        "replaced_by_technique_id IS NULL OR status = 'revoked'",
    )
    op.create_check_constraint(
        "ck_mitre_technique_catalog_technique_id_format",
        CATALOG,
        r"technique_id ~ '^T[0-9]{4}(\.[0-9]{3})?$'",
    )
    op.create_check_constraint(
        "ck_mitre_technique_catalog_subtechnique_has_parent",
        CATALOG,
        "is_subtechnique = (parent_technique_id IS NOT NULL)",
    )
    op.create_foreign_key(
        "fk_mitre_technique_catalog_replaced_by",
        CATALOG,
        CATALOG,
        ["replaced_by_technique_id"],
        ["technique_id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "mitre_tactics",
        sa.Column("tactic_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("shortname", sa.Text(), nullable=False),
        sa.Column(
            "synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(r"tactic_id ~ '^TA[0-9]{4}$'", name="ck_mitre_tactics_tactic_id_format"),
        sa.UniqueConstraint("name", name="uq_mitre_tactics_name"),
        sa.UniqueConstraint("shortname", name="uq_mitre_tactics_shortname"),
    )


def downgrade() -> None:
    op.drop_table("mitre_tactics")
    # Revoked/deprecated rows didn't exist before this revision.
    op.execute(f"DELETE FROM {CATALOG} WHERE status <> 'active'")
    op.drop_constraint("fk_mitre_technique_catalog_replaced_by", CATALOG, type_="foreignkey")
    for name in (
        "ck_mitre_technique_catalog_subtechnique_has_parent",
        "ck_mitre_technique_catalog_technique_id_format",
        "ck_mitre_technique_catalog_replaced_only_if_revoked",
        "ck_mitre_technique_catalog_status",
    ):
        op.drop_constraint(name, CATALOG, type_="check")
    op.drop_column(CATALOG, "replaced_by_technique_id")
    op.drop_column(CATALOG, "status")
