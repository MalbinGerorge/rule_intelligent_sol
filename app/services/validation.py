"""
Cross-checks ingested rules/building blocks against QRadar's own
reference endpoints, writing findings into validation_results.

Two checks per entity type, in both directions:
  - 'in_reference': every row we ingested — does it actually exist in
    QRadar's reference list? (catches stale/deleted rules still sitting
    in our DB)
  - 'in_ingested': every row in QRadar's reference list — did we
    actually ingest it? (catches pull failures — pagination bugs,
    permission gaps, etc. — rules_with_data silently missing something
    that genuinely exists)

Only failures get written to validation_results (a full audit log of
every passing row would bloat the table with no actionable value) — but
pass counts are still returned so the caller can report a clean summary.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def validate_rules(session: Session, customer_id: int) -> dict:
    session.execute(
        text("DELETE FROM validation_results WHERE customer_id = :c AND entity_type = 'rule'"),
        {"c": customer_id},
    )

    missing_from_reference = session.execute(
        text(
            """
            SELECT qradar_rule_id, identifier, name FROM rules r
            WHERE r.customer_id = :c AND r.object_type = 'RULE'
              AND NOT EXISTS (
                  SELECT 1 FROM rules_reference rr
                  WHERE rr.customer_id = r.customer_id AND rr.qradar_rule_id = r.qradar_rule_id
              )
            """
        ),
        {"c": customer_id},
    ).fetchall()

    missing_from_ingested = session.execute(
        text(
            """
            SELECT qradar_rule_id, identifier, name FROM rules_reference rr
            WHERE rr.customer_id = :c
              AND NOT EXISTS (
                  SELECT 1 FROM rules r
                  WHERE r.customer_id = rr.customer_id AND r.qradar_rule_id = rr.qradar_rule_id
              )
            """
        ),
        {"c": customer_id},
    ).fetchall()

    for qradar_rule_id, identifier, name in missing_from_reference:
        session.execute(
            text(
                """
                INSERT INTO validation_results (customer_id, entity_type, entity_ref, check_type, status, details)
                VALUES (:c, 'rule', :ref, 'in_reference', 'missing', :details)
                """
            ),
            {
                "c": customer_id,
                "ref": str(qradar_rule_id),
                "details": f"Ingested rule (identifier={identifier}, name={name!r}) not found in /analytics/rules — "
                           f"may have been deleted in QRadar since last pull, or the reference pull itself failed.",
            },
        )

    for qradar_rule_id, identifier, name in missing_from_ingested:
        session.execute(
            text(
                """
                INSERT INTO validation_results (customer_id, entity_type, entity_ref, check_type, status, details)
                VALUES (:c, 'rule', :ref, 'in_ingested', 'missing', :details)
                """
            ),
            {
                "c": customer_id,
                "ref": str(qradar_rule_id),
                "details": f"Rule in /analytics/rules (identifier={identifier}, name={name!r}) was not ingested via "
                           f"rules_with_data — check pagination, Allow-Hidden, or permissions.",
            },
        )

    total_ingested = session.execute(
        text("SELECT count(*) FROM rules WHERE customer_id = :c AND object_type = 'RULE'"), {"c": customer_id}
    ).scalar_one()
    total_reference = session.execute(
        text("SELECT count(*) FROM rules_reference WHERE customer_id = :c"), {"c": customer_id}
    ).scalar_one()

    return {
        "total_ingested": total_ingested,
        "total_reference": total_reference,
        "missing_from_reference": len(missing_from_reference),
        "missing_from_ingested": len(missing_from_ingested),
    }


def validate_building_blocks(session: Session, customer_id: int) -> dict:
    session.execute(
        text("DELETE FROM validation_results WHERE customer_id = :c AND entity_type = 'building_block'"),
        {"c": customer_id},
    )

    missing_from_reference = session.execute(
        text(
            """
            SELECT qradar_rule_id, identifier, name FROM rules r
            WHERE r.customer_id = :c AND r.object_type = 'BUILDING_BLOCK'
              AND NOT EXISTS (
                  SELECT 1 FROM building_blocks_reference bbr
                  WHERE bbr.customer_id = r.customer_id AND bbr.qradar_rule_id = r.qradar_rule_id
              )
            """
        ),
        {"c": customer_id},
    ).fetchall()

    missing_from_ingested = session.execute(
        text(
            """
            SELECT qradar_rule_id, identifier, name FROM building_blocks_reference bbr
            WHERE bbr.customer_id = :c
              AND NOT EXISTS (
                  SELECT 1 FROM rules r
                  WHERE r.customer_id = bbr.customer_id AND r.qradar_rule_id = bbr.qradar_rule_id
                    AND r.object_type = 'BUILDING_BLOCK'
              )
            """
        ),
        {"c": customer_id},
    ).fetchall()

    for qradar_rule_id, identifier, name in missing_from_reference:
        session.execute(
            text(
                """
                INSERT INTO validation_results (customer_id, entity_type, entity_ref, check_type, status, details)
                VALUES (:c, 'building_block', :ref, 'in_reference', 'missing', :details)
                """
            ),
            {
                "c": customer_id,
                "ref": str(qradar_rule_id),
                "details": f"Ingested building block (identifier={identifier}, name={name!r}) not found in "
                           f"/analytics/building_blocks.",
            },
        )

    for qradar_rule_id, identifier, name in missing_from_ingested:
        session.execute(
            text(
                """
                INSERT INTO validation_results (customer_id, entity_type, entity_ref, check_type, status, details)
                VALUES (:c, 'building_block', :ref, 'in_ingested', 'missing', :details)
                """
            ),
            {
                "c": customer_id,
                "ref": str(qradar_rule_id),
                "details": f"Building block in /analytics/building_blocks (identifier={identifier}, name={name!r}) "
                           f"was not ingested as object_type=BUILDING_BLOCK via rules_with_data.",
            },
        )

    total_ingested = session.execute(
        text("SELECT count(*) FROM rules WHERE customer_id = :c AND object_type = 'BUILDING_BLOCK'"),
        {"c": customer_id},
    ).scalar_one()
    total_reference = session.execute(
        text("SELECT count(*) FROM building_blocks_reference WHERE customer_id = :c"), {"c": customer_id}
    ).scalar_one()

    return {
        "total_ingested": total_ingested,
        "total_reference": total_reference,
        "missing_from_reference": len(missing_from_reference),
        "missing_from_ingested": len(missing_from_ingested),
    }