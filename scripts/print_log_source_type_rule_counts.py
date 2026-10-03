"""
Diagnostic: for each log source type genuinely onboarded for a
customer (from log_sources_reference, joined to
log_source_types_reference for the real name -- the SAME query
LogSourceGapAnalyzer uses), checks Neo4j directly for how many rules
require that exact type name. Reveals whether "0 gaps" reflects
genuine coverage, or a silent name mismatch between the two systems.

Usage:
    uv run python scripts/print_log_source_type_rule_counts.py --name cotecna
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

from sqlalchemy import text

from app.db.session import engine
from app.graph.client import get_driver, close_driver


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="customer name, e.g. cotecna")
    args = parser.parse_args()

    with engine.connect() as conn:
        customer_id = conn.execute(
            text("SELECT id FROM customers WHERE name = :name"), {"name": args.name}
        ).scalar_one_or_none()
        if customer_id is None:
            raise SystemExit(f"No customer named '{args.name}'.")

        # SAME query LogSourceGapAnalyzer._get_onboarded_log_source_types uses
        onboarded = conn.execute(
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
                ORDER BY lstr.name
                """
            ),
            {"customer_id": customer_id},
        ).mappings().all()

    driver = get_driver()
    try:
        with driver.session() as session:
            print(f"\n{args.name}: {len(onboarded)} onboarded log source type(s) (from log_sources_reference)\n")
            for row in onboarded:
                result = session.run(
                    """
                    MATCH (r:Rule {customer_id: $customer_id})-[:REQUIRES_LOGSOURCE_TYPE]->(lst:LogSourceType {name: $name})
                    WHERE NOT r.is_superseded
                    RETURN count(DISTINCT r) AS rule_count
                    """,
                    customer_id=customer_id,
                    name=row["name"],
                )
                rule_count = result.single()["rule_count"]
                flag = "" if rule_count > 0 else "  <-- GAP (0 rule coverage)"
                print(f"  type_id={row['qradar_type_id']:<6} rules={rule_count:<4} {row['name']}{flag}")
    finally:
        close_driver()


if __name__ == "__main__":
    main()