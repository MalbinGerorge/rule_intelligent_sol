"""
Combined orchestrator for everything extracted from rule_xml — BB
references (rule_building_blocks) AND conditions (rule_conditions).

Both MUST happen together, sharing one needs_reparse reset. Splitting
this into two separate functions that each independently read
needs_reparse and mark it false would be a real bug: whichever ran
second would find nothing left to process, since the first already
flipped the flag off. One combined pass per rule avoids that entirely.

Supersedes app/services/bb_relationship_ingest.py's standalone
sync_rule_building_blocks as the actual entrypoint to call — that
function's logic is reused here unchanged, just no longer paired with
its own flag reset.
"""
from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.bb_parse_scheduler import get_rules_needing_bb_parse, mark_bb_parsed
from app.services.rule_xml_parser import extract_bb_references
from app.services.rule_condition_parser import parse_rule_conditions


def sync_rule_xml_data(db: Session, customer_id: int) -> dict:
    """
    For every rule/BB with needs_reparse = true:
      1. Parse rule_xml for BB references -> rebuild rule_building_blocks
      2. Parse rule_xml for conditions -> rebuild rule_conditions
      3. Reset needs_reparse = false (ONLY after both succeed)

    Returns summary counts.
    """
    to_parse = get_rules_needing_bb_parse(db, customer_id)
    rules_processed = 0
    bb_refs_inserted = 0
    conditions_inserted = 0

    for rule in to_parse:
        raw_json = rule["raw_json"]
        rule_xml = None
        if raw_json:
            data = raw_json if isinstance(raw_json, dict) else json.loads(raw_json)
            rule_xml = data.get("rule_xml")

        # -- BB references --
        bb_refs = extract_bb_references(rule_xml)
        db.execute(text("DELETE FROM rule_building_blocks WHERE rule_id = :rule_id"), {"rule_id": rule["id"]})
        for ref in bb_refs:
            db.execute(
                text(
                    """
                    INSERT INTO rule_building_blocks (rule_id, bb_id, raw_xml_snippet)
                    VALUES (:rule_id, :bb_id, :raw_xml_snippet)
                    """
                ),
                {"rule_id": rule["id"], "bb_id": ref["bb_identifier"], "raw_xml_snippet": ref["raw_xml_snippet"]},
            )
            bb_refs_inserted += 1

        # -- Conditions --
        conditions = parse_rule_conditions(rule_xml)
        db.execute(text("DELETE FROM rule_conditions WHERE rule_id = :rule_id"), {"rule_id": rule["id"]})
        for i, cond in enumerate(conditions):
            db.execute(
                text(
                    """
                    INSERT INTO rule_conditions (rule_id, sequence_order, test_class, negated, raw_text, structured_data)
                    VALUES (:rule_id, :sequence_order, :test_class, :negated, :raw_text, :structured_data)
                    """
                ),
                {
                    "rule_id": rule["id"],
                    "sequence_order": i,
                    "test_class": cond["test_class"],
                    "negated": cond["negated"],
                    "raw_text": cond.get("raw_text"),
                    "structured_data": json.dumps(cond),
                },
            )
            conditions_inserted += 1

        mark_bb_parsed(db, rule["id"])
        rules_processed += 1

    return {
        "rules_processed": rules_processed,
        "bb_refs_inserted": bb_refs_inserted,
        "conditions_inserted": conditions_inserted,
    }