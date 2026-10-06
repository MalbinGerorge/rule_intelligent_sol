"""store any as NULL in event property scope columns

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-06

Phase 2b-2 of the database redesign (docs/database/design.md).

QRadar marks an expression's scope as "not restricted / applies to any"
with -1 (and with 0 in qid / low_level_category_id on AQL expressions).
Those values were stored as if they were real IDs. They become NULL
(= any), and CHECK constraints stop them from coming back:

    log_source_id, qid, low_level_category_id   NULL or > 0
    log_source_type_id                          NULL, or not -1 / 0  (a few
                                                AQL expressions carry large
                                                negative type IDs of unknown
                                                meaning; they are kept)
    capture_group                               NULL or >= 0 (0 = whole match)

Readers changed in the same release: the simulator's DSM property
extractor (matched -1) and the Rule Analyzer's extraction-configured tool.
Ingestion validates QRadar payloads with
app.integrations.qradar.models.QRadarPropertyExpression.

Downgrade restores -1 for NULL scope values; it can't tell which qid /
category values were 0 before, so those also come back as -1.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "custom_event_property_expressions"
CHECKS = {
    "ck_cepe_log_source_id_real_or_any": "log_source_id IS NULL OR log_source_id > 0",
    "ck_cepe_qid_real_or_any": "qid IS NULL OR qid > 0",
    "ck_cepe_low_level_category_id_real_or_any": "low_level_category_id IS NULL OR low_level_category_id > 0",
    "ck_cepe_log_source_type_id_not_any_marker": "log_source_type_id IS NULL OR log_source_type_id NOT IN (-1, 0)",
    "ck_cepe_capture_group_non_negative": "capture_group IS NULL OR capture_group >= 0",
}
SCOPE_COLUMNS = ("log_source_type_id", "log_source_id", "qid", "low_level_category_id")


def upgrade() -> None:
    # Pre-check: the only non-positive values must be the known markers, plus
    # the large negative type IDs that are kept. Anything else is new data
    # this migration wasn't written for.
    unexpected = (
        op.get_bind()
        .execute(
            sa.text(
                f"""
                SELECT count(*) FROM {TABLE}
                WHERE log_source_id < -1
                   OR qid < -1
                   OR low_level_category_id < -1
                   OR (log_source_type_id < -1 AND log_source_type_id > -2147483000)
                   OR capture_group < 0
                """
            )
        )
        .scalar()
    )
    if unexpected:
        raise RuntimeError(f"{TABLE}: {unexpected} rows with unexpected negative values")

    op.execute(f"UPDATE {TABLE} SET log_source_type_id = NULL WHERE log_source_type_id IN (-1, 0)")
    op.execute(f"UPDATE {TABLE} SET log_source_id = NULL WHERE log_source_id IN (-1, 0)")
    op.execute(f"UPDATE {TABLE} SET qid = NULL WHERE qid IN (-1, 0)")
    op.execute(
        f"UPDATE {TABLE} SET low_level_category_id = NULL WHERE low_level_category_id IN (-1, 0)"
    )
    for name, condition in CHECKS.items():
        op.create_check_constraint(name, TABLE, condition)


def downgrade() -> None:
    for name in CHECKS:
        op.drop_constraint(name, TABLE, type_="check")
    for column in SCOPE_COLUMNS:
        op.execute(f"UPDATE {TABLE} SET {column} = -1 WHERE {column} IS NULL")
