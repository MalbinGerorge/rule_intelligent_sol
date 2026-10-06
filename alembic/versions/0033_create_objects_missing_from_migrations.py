"""create objects that existed only in the dev database

Revision ID: 0033
Revises: 202609271707
Create Date: 2026-10-06 14:53:37.258498

Three objects existed in the development database but were never created
by a migration (found by scripts/db_migration_check.py), so every database
built from migrations -- CI, tests, a new environment -- lacked them:

- UNIQUE (rule_id, customer_id, role) and UNIQUE (sigma_id) on
  rule_yaml_representations, declared in the ORM model
  (app/db/models/rule_yaml_representation.py) but never migrated
- the pg_trgm extension

Each is created only if missing: on a database that already has it (the
development database) this migration changes nothing; on a new one it
creates it. Constraint names match the ORM model.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0033"
down_revision: str | None = "202609271707"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UNIQUE_CONSTRAINTS = {
    "uq_rule_yaml_rule_customer_role": "(rule_id, customer_id, role)",
    "uq_rule_yaml_sigma_id": "(sigma_id)",
}


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, columns in UNIQUE_CONSTRAINTS.items():
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = '{name}'
                      AND conrelid = 'rule_yaml_representations'::regclass
                ) THEN
                    ALTER TABLE rule_yaml_representations
                        ADD CONSTRAINT {name} UNIQUE {columns};
                END IF;
            END $$;
            """
        )


def downgrade() -> None:
    # Back to the schema the migrations built before this revision. On the
    # development database this also removes the objects that had been
    # created by hand; re-run `alembic upgrade` to restore them.
    for name in UNIQUE_CONSTRAINTS:
        op.execute(f"ALTER TABLE rule_yaml_representations DROP CONSTRAINT IF EXISTS {name}")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
