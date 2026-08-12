"""
Orchestrates BB-reference extraction for rules flagged as needing it
(rules.needs_reparse = true), rebuilding rule_building_blocks per rule
via delete-then-insert — so a rule that drops BB B and adds BB C ends
up with exactly the current set, never a stale mix of old and new.

rule_building_blocks is purely a results/mapper table here — it plays
no part in deciding what needs re-parsing (that's rules.needs_reparse,
set during ingestion).
"""
from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.bb_parse_scheduler import get_rules_needing_bb_parse, mark_bb_parsed
from app.services.rule_xml_parser import extract_bb_references


def sync_rule_building_blocks(db: Session, customer_id: int) -> dict:
    """
    For every rule/BB with needs_reparse = true:
      1. Parse rule_xml for BB references
      2. Delete existing rule_building_blocks rows for that rule
      3. Insert the freshly-extracted set
      4. Reset needs_reparse = false

    Returns summary counts.
    """
    to_parse = get_rules_needing_bb_parse(db, customer_id)
    rules_processed = 0
    refs_inserted = 0

    for rule in to_parse:
        raw_json = rule["raw_json"]
        rule_xml = None
        if raw_json:
            data = raw_json if isinstance(raw_json, dict) else json.loads(raw_json)
            rule_xml = data.get("rule_xml")

        refs = extract_bb_references(rule_xml)

        db.execute(text("DELETE FROM rule_building_blocks WHERE rule_id = :rule_id"), {"rule_id": rule["id"]})

        for ref in refs:
            db.execute(
                text(
                    """
                    INSERT INTO rule_building_blocks (rule_id, bb_id, raw_xml_snippet)
                    VALUES (:rule_id, :bb_id, :raw_xml_snippet)
                    """
                ),
                {"rule_id": rule["id"], "bb_id": ref["bb_identifier"], "raw_xml_snippet": ref["raw_xml_snippet"]},
            )
            refs_inserted += 1

        mark_bb_parsed(db, rule["id"])
        rules_processed += 1

    return {"rules_processed": rules_processed, "refs_inserted": refs_inserted}