"""
Validates ingested rules and building blocks against QRadar's reference
endpoints (rules_reference, building_blocks_reference), writing any
mismatches into validation_results.

Usage:
    uv run python scripts/run_validation.py --name cotecna

Run this after scripts/ingest.py — validation compares data already in
Postgres, it doesn't hit the QRadar API itself.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

from sqlalchemy import text

from app.db.session import engine
from app.services.validation import validate_rules, validate_building_blocks


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

    with engine.begin() as session:
        rule_summary = validate_rules(session, customer_id)
        bb_summary = validate_building_blocks(session, customer_id)

    print("=== Rules ===")
    print(f"Ingested: {rule_summary['total_ingested']}  |  Reference: {rule_summary['total_reference']}")
    print(f"Missing from reference (stale in our DB): {rule_summary['missing_from_reference']}")
    print(f"Missing from ingested (we failed to pull): {rule_summary['missing_from_ingested']}")

    print("\n=== Building Blocks ===")
    print(f"Ingested: {bb_summary['total_ingested']}  |  Reference: {bb_summary['total_reference']}")
    print(f"Missing from reference (stale in our DB): {bb_summary['missing_from_reference']}")
    print(f"Missing from ingested (we failed to pull): {bb_summary['missing_from_ingested']}")

    total_issues = sum(rule_summary.values()) - rule_summary["total_ingested"] - rule_summary["total_reference"]
    total_issues += sum(bb_summary.values()) - bb_summary["total_ingested"] - bb_summary["total_reference"]

    if total_issues == 0:
        print("\nAll clear — every rule and building block matches between ingested data and QRadar's reference.")
    else:
        print(f"\n{total_issues} issue(s) found — see validation_results table for details:")
        print("  SELECT entity_type, entity_ref, check_type, details FROM validation_results "
              f"WHERE customer_id = {customer_id};")


if __name__ == "__main__":
    main()