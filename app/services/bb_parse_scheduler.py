"""
Decides which rules actually need their rule_xml re-parsed for BB
references — by reading rules.needs_reparse directly.

The actual "did this rule change" decision happens ONCE, at ingest time
(see rule_ingest.upsert_rules), by comparing the OLD stored updated_at
against the NEWLY incoming one before overwriting it — both are
QRadar's own modification_date, never our server's wall clock.

rule_building_blocks has no role in this decision at all — it's purely
a results table, populated by whatever the parse finds.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def get_rules_needing_bb_parse(db: Session, customer_id: int) -> list[dict]:
    """Returns rows (id, qradar_rule_id, name, raw_json) for every rule/BB
    currently flagged as needing (re-)parsing."""
    rows = db.execute(
        text(
            """
            SELECT id, qradar_rule_id, name, raw_json
            FROM rules
            WHERE customer_id = :customer_id AND needs_reparse = true
            """
        ),
        {"customer_id": customer_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def mark_bb_parsed(db: Session, rule_id: int) -> None:
    """Call after successfully re-parsing (and rebuilding
    rule_building_blocks) for one rule."""
    db.execute(
        text("UPDATE rules SET needs_reparse = false WHERE id = :rule_id"),
        {"rule_id": rule_id},
    )