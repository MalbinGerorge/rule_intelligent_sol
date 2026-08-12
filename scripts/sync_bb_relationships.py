"""
Extracts BB references AND conditions from rule_xml, syncing both
rule_building_blocks and rule_conditions together — only for rules that
changed since the last parse.

Usage:
    uv run python scripts/sync_bb_relationships.py --name cotecna
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

from sqlalchemy import text

from app.db.session import engine
from app.services.rule_xml_sync import sync_rule_xml_data


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
        result = sync_rule_xml_data(session, customer_id)

    print(f"Rules re-parsed: {result['rules_processed']}")
    print(f"BB references inserted: {result['bb_refs_inserted']}")
    print(f"Conditions inserted: {result['conditions_inserted']}")


if __name__ == "__main__":
    main()