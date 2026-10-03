"""
Manual check: run the log-source-type gap analysis for one customer,
print the results. Not a production endpoint -- just for verifying
the LogSourceGapAnalyzer's real output against real Postgres/Neo4j
data before wiring it into an API.

Usage:
    uv run python scripts/check_log_source_gaps.py --name cotecna
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.db.session import engine
from app.graph.client import get_driver, close_driver
from app.recommendations.log_source_gap_analyzer import LogSourceGapAnalyzer


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

    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    driver = get_driver()

    try:
        analyzer = LogSourceGapAnalyzer(db, driver)
        gaps = analyzer.analyze(customer_id)

        print(f"\n{len(gaps)} gap(s) found for {args.name}:\n")
        for g in gaps:
            print(f"- {g.log_source_type_name} (type id {g.qradar_type_id})")
            print(f"  Peers with coverage: {g.peer_customer_names}")
            print(f"  {len(g.suggested_rules)} suggested rule(s):")
            for s in g.suggested_rules:
                print(f"    - [{s.source_customer_name}] {s.title} (level: {s.level})")
            print()
    finally:
        db.close()
        close_driver()


if __name__ == "__main__":
    main()