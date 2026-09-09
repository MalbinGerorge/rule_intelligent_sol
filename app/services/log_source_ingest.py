"""
Ingests QRadar's CONFIGURED log source instances (not types) -- the
real "onboarded" signal, distinct from log_source_types_reference's
software-catalog data. Same upsert pattern as everywhere else in this
project: pull once, cache, join against it going forward.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session


def upsert_log_sources_reference(session: Session, customer_id: int, pages: list[str]) -> int:
    """Ingest log_sources pages. Returns rows upserted."""
    count = 0
    for page in pages:
        records = json.loads(page)
        for r in records:
            status_obj = r.get("status") or {}
            last_event_ms = r.get("last_event_time")
            session.execute(
                text(
                    """
                    INSERT INTO log_sources_reference (
                        customer_id, qradar_log_source_id, name, type_id, enabled,
                        status, last_event_at, average_eps, raw_json
                    ) VALUES (
                        :customer_id, :qradar_log_source_id, :name, :type_id, :enabled,
                        :status, :last_event_at, :average_eps, :raw_json
                    )
                    ON CONFLICT (customer_id, qradar_log_source_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        type_id = EXCLUDED.type_id,
                        enabled = EXCLUDED.enabled,
                        status = EXCLUDED.status,
                        last_event_at = EXCLUDED.last_event_at,
                        average_eps = EXCLUDED.average_eps,
                        raw_json = EXCLUDED.raw_json,
                        synced_at = now()
                    """
                ),
                {
                    "customer_id": customer_id,
                    "qradar_log_source_id": r["id"],
                    "name": r.get("name"),
                    "type_id": r.get("type_id"),
                    "enabled": r.get("enabled"),
                    "status": status_obj.get("status"),
                    "last_event_at": (
                        datetime.fromtimestamp(last_event_ms / 1000, tz=timezone.utc) if last_event_ms else None
                    ),
                    "average_eps": r.get("average_eps"),
                    "raw_json": json.dumps(r),
                },
            )
            count += 1
    return count