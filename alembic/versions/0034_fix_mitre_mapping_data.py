"""fix mitre mapping tactic ids and use NULL for tactic-only rows

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-06

Phase 2b-1 of the database redesign (docs/database/design.md).

1. Tactic IDs. QRadar consoles send MITRE coverage keyed either by tactic
   ID ({"TA0002": {"name": "Execution"}}) or by tactic NAME
   ({"Execution": {"id": "TA0002"}}). The parser assumed the first shape,
   so for consoles using the second it stored the name in tactic_id and an
   empty tactic name (1,172 rows for one customer in the development data).
   The correct ID is taken from QRadar's own payload in raw_json; the
   name moves to `tactic`.

2. Tactic-only rows (a tactic with no technique) used technique_id = ''
   because a plain UNIQUE treats NULLs as distinct and re-ingestion would
   have duplicated them. The constraint becomes UNIQUE NULLS NOT DISTINCT
   (Postgres 15+) first, then '' becomes NULL in technique_id and
   technique_name.

Pre-checks stop the migration, before any change, if a tactic can't be
resolved from raw_json or the fix would collide with an existing row.

Downgrade restores the schema and the '' values. It does not put tactic
names back into tactic_id: that was wrong data, not a previous design.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "uq_mitre_mappings_rule_tactic_technique"
NOT_AN_ID = "tactic_id !~ '^TA[0-9]{4}$'"

# For each row keyed by tactic name: the TA#### id QRadar sent for that key.
RESOLVED = f"""
    SELECT m.id, m.tactic_id AS tactic_name, min(r.value -> 'mapping' -> m.tactic_id ->> 'id') AS tactic_id
    FROM mitre_mappings m
    CROSS JOIN LATERAL jsonb_each(m.raw_json) r
    WHERE m.{NOT_AN_ID}
    GROUP BY m.id, m.tactic_id
"""


def _scalar(sql: str) -> int:
    return op.get_bind().execute(sa.text(sql)).scalar()


def upgrade() -> None:
    to_fix = _scalar(f"SELECT count(*) FROM mitre_mappings WHERE {NOT_AN_ID}")
    unresolved = _scalar(
        f"SELECT count(*) FROM ({RESOLVED}) x WHERE x.tactic_id IS NULL OR x.tactic_id !~ '^TA[0-9]{{4}}$'"
    )
    resolved = _scalar(f"SELECT count(*) FROM ({RESOLVED}) x")
    if unresolved or resolved != to_fix:
        raise RuntimeError(
            f"mitre_mappings: {to_fix} rows keyed by tactic name, {resolved} found in raw_json, "
            f"{unresolved} without a valid TA#### id; refusing to guess"
        )
    collisions = _scalar(
        f"""
        SELECT count(*) FROM ({RESOLVED}) x
        JOIN mitre_mappings m ON m.id = x.id
        JOIN mitre_mappings other
          ON other.rule_id = m.rule_id AND other.tactic_id = x.tactic_id
         AND other.technique_id = m.technique_id AND other.id <> m.id
        """
    )
    if collisions:
        raise RuntimeError(
            f"mitre_mappings: fixing tactic ids would create {collisions} duplicates"
        )

    # 1. tactic name -> `tactic`, QRadar's TA#### id -> `tactic_id`
    op.execute(
        f"""
        UPDATE mitre_mappings m
        SET tactic = x.tactic_name, tactic_id = x.tactic_id
        FROM ({RESOLVED}) x
        WHERE m.id = x.id
        """
    )

    # 2. NULL-safe uniqueness, then '' -> NULL
    op.drop_constraint(CONSTRAINT, "mitre_mappings", type_="unique")
    op.execute(
        f"ALTER TABLE mitre_mappings ADD CONSTRAINT {CONSTRAINT} "
        "UNIQUE NULLS NOT DISTINCT (rule_id, tactic_id, technique_id)"
    )
    op.alter_column("mitre_mappings", "technique_id", existing_type=sa.Text(), nullable=True)
    op.execute("UPDATE mitre_mappings SET technique_id = NULL WHERE technique_id = ''")
    op.execute("UPDATE mitre_mappings SET technique_name = NULL WHERE technique_name = ''")


def downgrade() -> None:
    op.execute("UPDATE mitre_mappings SET technique_name = '' WHERE technique_id IS NULL")
    op.execute("UPDATE mitre_mappings SET technique_id = '' WHERE technique_id IS NULL")
    op.alter_column("mitre_mappings", "technique_id", existing_type=sa.Text(), nullable=False)
    op.drop_constraint(CONSTRAINT, "mitre_mappings", type_="unique")
    op.create_unique_constraint(
        CONSTRAINT, "mitre_mappings", ["rule_id", "tactic_id", "technique_id"]
    )
