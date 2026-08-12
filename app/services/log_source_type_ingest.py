"""
Ingests QRadar's log source type catalog — resolves DeviceTypeID_Test's
numeric codes to real names (e.g. 12 -> "Microsoft Windows Security
Event Log"). Same upsert pattern as rules_reference/mitre_mappings:
pull once, cache in Postgres, join against it going forward.
"""
from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.orm import Session


def upsert_log_source_types_reference(session: Session, customer_id: int, pages: list[str]) -> int:
    """Ingest log_source_types pages. Returns rows upserted."""
    count = 0
    for page in pages:
        records = json.loads(page)
        for r in records:
            session.execute(
                text(
                    """
                    INSERT INTO log_source_types_reference (
                        customer_id, qradar_type_id, name, custom, internal, raw_json
                    ) VALUES (
                        :customer_id, :qradar_type_id, :name, :custom, :internal, :raw_json
                    )
                    ON CONFLICT (customer_id, qradar_type_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        custom = EXCLUDED.custom,
                        internal = EXCLUDED.internal,
                        raw_json = EXCLUDED.raw_json,
                        synced_at = now()
                    """
                ),
                {
                    "customer_id": customer_id,
                    "qradar_type_id": r["id"],
                    "name": r.get("name"),
                    "custom": r.get("custom"),
                    "internal": r.get("internal"),
                    "raw_json": json.dumps(r),
                },
            )
            count += 1
    return count