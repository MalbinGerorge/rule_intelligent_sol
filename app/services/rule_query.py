"""Read-side query logic for rule_summary.

Returns plain dicts — deliberately no Pydantic/schema import here.
Schemas are an API/HTTP concern (app/api/schemas/), not a service-layer
concern; converting a row into a response shape is the endpoint's job.
This keeps the service layer reusable by anything (CLI scripts, a
future worker, tests) without dragging in FastAPI's response contracts.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def list_rules(
    db: Session,
    customer_id: int,
    object_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    query = "SELECT * FROM rule_summary WHERE customer_id = :customer_id"
    params: dict = {"customer_id": customer_id, "limit": limit, "offset": offset}
    if object_type:
        query += " AND object_type = :object_type"
        params["object_type"] = object_type
    query += " ORDER BY name LIMIT :limit OFFSET :offset"

    rows = db.execute(text(query), params).mappings().all()
    return [dict(r) for r in rows]


def get_rule_by_id(db: Session, rule_id: int) -> dict | None:
    row = db.execute(
        text("SELECT * FROM rule_summary WHERE id = :id"), {"id": rule_id}
    ).mappings().first()
    return dict(row) if row else None


def get_health_metrics(db: Session, customer_id: int) -> dict:
    """
    Some QRadar rules AND building blocks exist as two linked physical
    rows (a SYSTEM-default half and a custom-GUID half), tied together
    via linked_rule_identifier pointing at each other. QRadar's own UI
    counts each pair as ONE logical item; our `rules` table correctly
    has two rows per pair, since that's what the API returns. Counting
    raw rows would overcount vs. QRadar's UI — confirmed against real
    data on both sides:
      - rules: 576 raw rows vs. 559 in QRadar's UI -> 17 linked pairs
      - building blocks: 336 raw rows vs. 329 in QRadar's UI -> 7 linked pairs

    Fix: group by LEAST(identifier, linked_rule_identifier) for BOTH
    object types — this gives both halves of a pair the same value
    (Postgres's LEAST/GREATEST ignore NULLs, so an unlinked row just
    groups by its own identifier, alone in its own group).

    For rules specifically: a pair counts as "enabled" if EITHER half is
    enabled, and "triggered" if EITHER half has fired — computed via
    bool_or() at the pair level, BEFORE splitting into triggered/
    not-triggered. Filtering raw rows independently per bucket risks
    double-counting a pair where only one half triggered.
    """
    row = db.execute(
        text(
            """
            WITH rule_pairs AS (
                SELECT
                    LEAST(identifier, linked_rule_identifier) AS pair_key,
                    bool_or(enabled) AS any_enabled,
                    bool_or(last_event_at IS NOT NULL) AS any_triggered
                FROM rule_summary
                WHERE customer_id = :customer_id AND object_type = 'RULE'
                GROUP BY LEAST(identifier, linked_rule_identifier)
            ),
            bb_pairs AS (
                SELECT LEAST(identifier, linked_rule_identifier) AS pair_key
                FROM rule_summary
                WHERE customer_id = :customer_id AND object_type = 'BUILDING_BLOCK'
                GROUP BY LEAST(identifier, linked_rule_identifier)
            )
            SELECT
                (SELECT count(*) FROM rule_pairs) AS total_rules,
                (SELECT count(*) FROM bb_pairs) AS total_building_blocks,
                (SELECT count(*) FROM rule_pairs WHERE any_enabled) AS enabled_rules,
                (SELECT count(*) FROM rule_pairs WHERE NOT any_enabled) AS disabled_rules,
                (SELECT count(*) FROM rule_pairs WHERE any_enabled AND any_triggered) AS enabled_triggered,
                (SELECT count(*) FROM rule_pairs WHERE any_enabled AND NOT any_triggered) AS enabled_not_triggered
            """
        ),
        {"customer_id": customer_id},
    ).mappings().first()
    return dict(row)