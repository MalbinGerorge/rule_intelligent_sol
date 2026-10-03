"""
Ingests rules_offense_contributions into rule_offense_contributions.

Requires `rules` to already be ingested for this customer — each
contribution's rule_id (QRadar's numeric id) is resolved to our internal
rules.id via a lookup. Contributions whose rule_id isn't found yet are
skipped and counted, not silently dropped, so ingestion order issues are
visible rather than hidden.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session


def _epoch_ms_to_dt(value) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def upsert_offense_contributions(session: Session, customer_id: int, pages: list[str]) -> tuple[int, int]:
    """Returns (upserted_count, skipped_no_matching_rule_count)."""
    upserted = 0
    skipped = 0
    for page in pages:
        records = json.loads(page)
        for c in records:
            qradar_rule_id = c.get("rule_id")
            local_rule_id = session.execute(
                text("SELECT id FROM rules WHERE customer_id = :customer_id AND qradar_rule_id = :qradar_rule_id"),
                {"customer_id": customer_id, "qradar_rule_id": qradar_rule_id},
            ).scalar_one_or_none()

            if local_rule_id is None:
                skipped += 1
                continue

            session.execute(
                text(
                    """
                    INSERT INTO rule_offense_contributions (
                        customer_id, rule_id, qradar_contribution_id, qradar_rule_id,
                        rule_name, rule_type, offense_id, event_count,
                        first_event_epoch_ms, last_event_epoch_ms, first_event_at, last_event_at,
                        raw_json
                    ) VALUES (
                        :customer_id, :rule_id, :qradar_contribution_id, :qradar_rule_id,
                        :rule_name, :rule_type, :offense_id, :event_count,
                        :first_event_epoch_ms, :last_event_epoch_ms, :first_event_at, :last_event_at,
                        :raw_json
                    )
                    ON CONFLICT (customer_id, qradar_contribution_id) DO UPDATE SET
                        rule_id = EXCLUDED.rule_id,
                        rule_name = EXCLUDED.rule_name,
                        rule_type = EXCLUDED.rule_type,
                        offense_id = EXCLUDED.offense_id,
                        event_count = EXCLUDED.event_count,
                        first_event_epoch_ms = EXCLUDED.first_event_epoch_ms,
                        last_event_epoch_ms = EXCLUDED.last_event_epoch_ms,
                        first_event_at = EXCLUDED.first_event_at,
                        last_event_at = EXCLUDED.last_event_at,
                        raw_json = EXCLUDED.raw_json,
                        synced_at = now()
                    """
                ),
                {
                    "customer_id": customer_id,
                    "rule_id": local_rule_id,
                    "qradar_contribution_id": c["id"],
                    "qradar_rule_id": qradar_rule_id,
                    "rule_name": c.get("rule_name"),
                    "rule_type": c.get("rule_type"),
                    "offense_id": str(c.get("offense_id")) if c.get("offense_id") is not None else None,
                    "event_count": c.get("event_count"),
                    "first_event_epoch_ms": c.get("first_event"),
                    "last_event_epoch_ms": c.get("last_event"),
                    "first_event_at": _epoch_ms_to_dt(c.get("first_event")),
                    "last_event_at": _epoch_ms_to_dt(c.get("last_event")),
                    "raw_json": json.dumps(c),
                },
            )
            upserted += 1
    return upserted, skipped