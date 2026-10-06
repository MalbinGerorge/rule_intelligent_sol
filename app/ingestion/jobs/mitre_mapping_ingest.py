"""
Ingests MITRE coverage results into mitre_mappings.

Input is the list saved by test_pull_data.py:
    [{"identifier": "SYSTEM-1443", "mitre_coverage": {<rule_name>: {...}}}, ...]

Flattens the nested {rule_name: {mapping: {<tactic key>: {techniques: {...}}}}}
shape into one row per (rule, tactic, technique). A tactic with no techniques
still gets one row, with technique_id/technique_name NULL; the unique
constraint is NULLS NOT DISTINCT, so re-ingestion still dedupes those rows.

QRadar consoles send the tactic in one of two shapes (both seen in real data):
    {"TA0002": {"name": "Execution", ...}}      key = tactic ID
    {"Execution": {"id": "TA0002", ...}}        key = tactic name
parse_mitre_coverage normalizes both to tactic_id = "TA0002", tactic = "Execution".
"""

from __future__ import annotations

import json
import re

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = structlog.get_logger(__name__)


TACTIC_ID = re.compile(r"^TA\d{4}$")


def _tactic(key: str, info: dict) -> tuple[str | None, str | None]:
    """(tactic_id, tactic_name) from either QRadar shape; tactic_id is None
    if neither the key nor the payload holds a valid TA#### ID."""
    if TACTIC_ID.match(key):
        return key, info.get("name") or None
    tactic_id = info.get("id")
    return (tactic_id if tactic_id and TACTIC_ID.match(tactic_id) else None), key


def parse_mitre_coverage(raw: dict) -> list[dict]:
    """Flattens one rule's mitre_coverage payload into row dicts."""
    rows = []
    for rule_data in raw.values():
        mapping = rule_data.get("mapping", {})
        if not mapping:
            continue  # no coverage at all for this rule — no rows, which is correct
        for key, tactic_info in mapping.items():
            tactic_id, tactic_name = _tactic(key, tactic_info)
            if tactic_id is None:
                logger.warning("mitre_tactic_without_id_skipped", tactic_key=key)
                continue
            techniques = tactic_info.get("techniques", {})
            if not techniques:
                # tactic applies, but no specific technique
                rows.append(
                    {
                        "tactic_id": tactic_id,
                        "tactic": tactic_name,
                        "technique_id": None,
                        "technique_name": None,
                    }
                )
            else:
                for tech_name, tech_info in techniques.items():
                    rows.append(
                        {
                            "tactic_id": tactic_id,
                            "tactic": tactic_name,
                            "technique_id": tech_info.get("id") or None,
                            "technique_name": tech_name or None,
                        }
                    )
    return rows


def upsert_mitre_mappings(
    session: Session, customer_id: int, results: list[dict]
) -> tuple[int, int]:
    """Returns (upserted_row_count, skipped_no_matching_rule_count)."""
    upserted = 0
    skipped = 0
    for entry in results:
        identifier = entry.get("identifier")
        coverage = entry.get("mitre_coverage")
        if not coverage:
            continue  # a failed/errored fetch — nothing to ingest for this identifier

        local_rule_id = session.execute(
            text(
                "SELECT id FROM rules WHERE customer_id = :customer_id AND identifier = :identifier"
            ),
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
