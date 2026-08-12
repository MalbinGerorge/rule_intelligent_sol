"""
Fetches the raw rule_xml for a specific rule by name (partial match).

Usage:
    uv run python scripts/fetch_rule_xml.py --name cotecna --rule-name "Successful login after multiple Failed Login"
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import json

from sqlalchemy import text

from app.db.session import engine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="customer name, e.g. cotecna")
    parser.add_argument("--rule-name", required=True, help="partial rule name to search for")
    args = parser.parse_args()

    with engine.connect() as conn:
        customer_id = conn.execute(
            text("SELECT id FROM customers WHERE name = :name"), {"name": args.name}
        ).scalar_one_or_none()
        if customer_id is None:
            raise SystemExit(f"No customer named '{args.name}'.")

        rows = conn.execute(
            text(
                "SELECT name, raw_json FROM rules WHERE customer_id = :c AND name ILIKE :pattern"
            ),
            {"c": customer_id, "pattern": f"%{args.rule_name}%"},
        ).fetchall()

    if not rows:
        print("No matching rule found.")
        return

    for name, raw_json in rows:
        data = raw_json if isinstance(raw_json, dict) else json.loads(raw_json)
        rule_xml = data.get("rule_xml")
        print("=" * 70)
        print(f"RULE: {name}")
        print("=" * 70)
        print(rule_xml)
        print()


if __name__ == "__main__":
    main()