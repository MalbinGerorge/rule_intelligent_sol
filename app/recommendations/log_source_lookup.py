"""
Shared logic for resolving a customer's REAL onboarded log source
types -- used by BOTH LogSourceGapAnalyzer and MitreGapAnalyzer.
Extracted here specifically to avoid duplicating the same query in
two places -- a real risk of the two definitions silently drifting
apart over time if each analyzer maintained its own copy.

Confirmed correct source: log_sources_reference (configured
INSTANCES with real events seen), NOT log_source_types_reference
alone -- that table is QRadar's full supported-DSM catalog, identical
across every deployment, not customer-specific data. See project
notes for the real, confirmed bug this distinction fixed.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def get_onboarded_log_source_types(db: Session, customer_id: int) -> list[dict]:
    """Real, active log source types (qradar_type_id + name) this
    customer is genuinely onboarded on -- enabled=true AND at least
    one real event seen. "Configured but silent" doesn't count."""
    rows = db.execute(
        text(
            """
            SELECT DISTINCT lstr.qradar_type_id, lstr.name
            FROM log_sources_reference lsr
            JOIN log_source_types_reference lstr
                ON lstr.customer_id = lsr.customer_id AND lstr.qradar_type_id = lsr.type_id
            WHERE lsr.customer_id = :customer_id
              AND lsr.enabled = true
              AND lsr.last_event_at IS NOT NULL
              AND lstr.name IS NOT NULL
            """
        ),
        {"customer_id": customer_id},
    ).mappings().all()
    return [dict(r) for r in rows]