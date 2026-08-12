"""
Pulls one (or a few) sample <text> values per distinct test class, so we
can see whether QRadar's "when the event matches ..." sentence grammar
generalizes across different test types, or whether each test class has
its own distinct phrasing.

Usage:
    uv run python scripts/sample_text_by_class.py --name cotecna --samples-per-class 1
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import json
import xml.etree.ElementTree as ET
from collections import defaultdict

from sqlalchemy import text as sql_text

from app.db.session import engine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="customer name, e.g. cotecna")
    parser.add_argument("--samples-per-class", type=int, default=1)
    args = parser.parse_args()

    with engine.connect() as conn:
        customer_id = conn.execute(
            sql_text("SELECT id FROM customers WHERE name = :name"), {"name": args.name}
        ).scalar_one_or_none()
        if customer_id is None:
            raise SystemExit(f"No customer named '{args.name}'.")

        rows = conn.execute(
            sql_text("SELECT raw_json FROM rules WHERE customer_id = :c"), {"c": customer_id}
        ).fetchall()

    samples_by_class: dict[str, list[str]] = defaultdict(list)

    for (raw_json,) in rows:
        data = raw_json if isinstance(raw_json, dict) else json.loads(raw_json)
        rule_xml = data.get("rule_xml")
        if not rule_xml:
            continue
        try:
            root = ET.fromstring(rule_xml)
        except ET.ParseError:
            continue
        for test_el in root.iter("test"):
            name = test_el.get("name", "UNKNOWN").rsplit(".", 1)[-1]
            if len(samples_by_class[name]) >= args.samples_per_class:
                continue
            text_el = test_el.find("text")
            if text_el is not None and text_el.text:
                samples_by_class[name].append(text_el.text)

    for cls in sorted(samples_by_class.keys()):
        print(f"=== {cls} ===")
        for s in samples_by_class[cls]:
            print(f"  {s}")
        print()


if __name__ == "__main__":
    main()