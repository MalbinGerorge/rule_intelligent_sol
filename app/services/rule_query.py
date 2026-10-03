"""Read-side query logic for rule_summary.

Returns plain dicts -- deliberately no Pydantic/schema import here.
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


def list_canonical_rules(db: Session, customer_id: int) -> list[dict]:
    """One row per LOGICAL rule, deduplicating SYSTEM/OVERRIDE linked
    pairs -- prefers the OVERRIDE half (the currently-active, real
    detection logic) when a pair exists. CONFIRMED NECESSARY: every
    override rule creates exactly this pairing (17 confirmed pairs via
    get_health_metrics' own analysis, and directly confirmed against a
    real pair -- "Chained Exploit Followed by Suspicious Events",
    SYSTEM-1545 / 533efd4c-...) -- without this, batch processes like
    Sigma generation would silently process the STALE pre-override
    half instead of what's actually running, or double-process both
    halves as if they were two separate rules.

    Neither underlying source is wrong or gets modified -- `rules`
    correctly reflects QRadar's raw API (both halves genuinely exist),
    `rule_summary` correctly summarizes each row as-is. This is a
    THIRD, distinct need (one canonical id per logical rule), so it's
    resolved here, at query time, not by changing either source."""
    rows = db.execute(
        text(
            """
            WITH pairs AS (
                SELECT *, LEAST(identifier, linked_rule_identifier) AS pair_key
                FROM rule_summary
                WHERE customer_id = :customer_id AND object_type = 'RULE'
            )
            SELECT DISTINCT ON (pair_key) *
            FROM pairs
            ORDER BY pair_key, (origin = 'OVERRIDE') DESC
            """
        ),
        {"customer_id": customer_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def get_health_metrics(db: Session, customer_id: int) -> dict:
    """
    Some QRadar rules AND building blocks exist as two linked physical
    rows (a SYSTEM-default half and a custom-GUID half), tied together
    via linked_rule_identifier pointing at each other. QRadar's own UI
    counts each pair as ONE logical item; our `rules` table correctly
    has two rows per pair, since that's what the API returns. Counting
    raw rows would overcount vs. QRadar's UI -- confirmed against real
    data on both sides:
      - rules: 576 raw rows vs. 559 in QRadar's UI -> 17 linked pairs
      - building blocks: 336 raw rows vs. 329 in QRadar's UI -> 7 linked pairs

    Fix: group by LEAST(identifier, linked_rule_identifier) for BOTH
    object types -- this gives both halves of a pair the same value
    (Postgres's LEAST/GREATEST ignore NULLs, so an unlinked row just
    groups by its own identifier, alone in its own group).

    For rules specifically: a pair counts as "enabled" if EITHER half is
    enabled, and "triggered" if EITHER half has fired -- computed via
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