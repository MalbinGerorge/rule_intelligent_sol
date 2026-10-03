"""
Pulls real sample <test> blocks for a specific QRadar test class, so we
can see its exact parameter shape before designing a parser for it.

Usage:
    uv run python scripts/sample_test_class.py --name cotecna --test-class ArielFilterTest --limit 3
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import json
import xml.etree.ElementTree as ET

from sqlalchemy import text

from app.db.session import engine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="customer name, e.g. cotecna")
    parser.add_argument("--test-class", required=True, help="short class name, e.g. ArielFilterTest")
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()

    with engine.connect() as conn:
        customer_id = conn.execute(
            text("SELECT id FROM customers WHERE name = :name"), {"name": args.name}
        ).scalar_one_or_none()
        if customer_id is None:
            raise SystemExit(f"No customer named '{args.name}'.")

        rows = conn.execute(
            text("SELECT name, raw_json FROM rules WHERE customer_id = :c"), {"c": customer_id}
        ).fetchall()

    found = 0
    for rule_name, raw_json in rows:
        if found >= args.limit:
            break
        data = raw_json if isinstance(raw_json, dict) else json.loads(raw_json)
        rule_xml = data.get("rule_xml")
        if not rule_xml:
            continue
        try:
            root = ET.fromstring(rule_xml)
        except ET.ParseError:
            continue
        for test_el in root.iter("test"):
            name = test_el.get("name", "")
            if name.rsplit(".", 1)[-1] == args.test_class:
                found += 1
                print(f"=== Sample {found} — from rule: {rule_name!r} ===")
                print(ET.tostring(test_el, encoding="unicode"))
                print()
                if found >= args.limit:
                    break

    if found == 0:
        print(f"No samples found for test class '{args.test_class}'.")


if __name__ == "__main__":
    main()