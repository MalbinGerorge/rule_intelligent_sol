"""
Ingests MITRE coverage results into mitre_mappings.

Input is the list saved by test_pull_data.py:
    [{"identifier": "SYSTEM-1443", "mitre_coverage": {<rule_name>: {...}}}, ...]

Flattens the nested {rule_name: {mapping: {tactic_id: {techniques: {...}}}}}
shape into one row per (rule, tactic, technique) — a tactic with an empty
techniques dict still gets one row (technique_id = '', a real comparable
value rather than NULL, so the unique constraint / ON CONFLICT dedup
actually works on re-ingestion).
"""
from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.orm import Session


def parse_mitre_coverage(raw: dict) -> list[dict]:
    """Flattens one rule's mitre_coverage payload into row dicts."""
    rows = []
    for rule_name_key, rule_data in raw.items():
        mapping = rule_data.get("mapping", {})
        if not mapping:
            continue  # no coverage at all for this rule — no rows, which is correct
        for tactic_id, tactic_info in mapping.items():
            techniques = tactic_info.get("techniques", {})
            if not techniques:
                # tactic applies, but no specific technique — one row, technique_id = ''
                rows.append(
                    {
                        "tactic_id": tactic_id,
                        "tactic": tactic_info.get("name", ""),
                        "technique_id": "",
                        "technique_name": "",
                    }
                )
            else:
                for tech_name, tech_info in techniques.items():
                    rows.append(
                        {
                            "tactic_id": tactic_id,
                            "tactic": tactic_info.get("name", ""),
                            "technique_id": tech_info.get("id", ""),
                            "technique_name": tech_name,
                        }
                    )
    return rows


def upsert_mitre_mappings(session: Session, customer_id: int, results: list[dict]) -> tuple[int, int]:
    """Returns (upserted_row_count, skipped_no_matching_rule_count)."""
    upserted = 0
    skipped = 0
    for entry in results:
        identifier = entry.get("identifier")
        coverage = entry.get("mitre_coverage")
        if not coverage:
            continue  # a failed/errored fetch — nothing to ingest for this identifier

        local_rule_id = session.execute(
            text("SELECT id FROM rules WHERE customer_id = :customer_id AND identifier = :identifier"),
            {"customer_id": customer_id, "identifier": identifier},
        ).scalar_one_or_none()

        if local_rule_id is None:
            skipped += 1
            continue

        for row in parse_mitre_coverage(coverage):
            session.execute(
                text(
                    """
                    INSERT INTO mitre_mappings (
                        customer_id, rule_id, tactic_id, tactic, technique_id, technique_name, raw_json
                    ) VALUES (
                        :customer_id, :rule_id, :tactic_id, :tactic, :technique_id, :technique_name, :raw_json
                    )
                    ON CONFLICT (rule_id, tactic_id, technique_id) DO UPDATE SET
                        tactic = EXCLUDED.tactic,
                        technique_name = EXCLUDED.technique_name,
                        raw_json = EXCLUDED.raw_json,
                        synced_at = now()
                    """
                ),
                {
                    "customer_id": customer_id,
                    "rule_id": local_rule_id,
                    "tactic_id": row["tactic_id"],
                    "tactic": row["tactic"],
                    "technique_id": row["technique_id"],
                    "technique_name": row["technique_name"],
                    "raw_json": json.dumps(coverage),
                },
            )
            upserted += 1
    return upserted, skipped