"""
Reconnaissance script — catalogs every distinct QRadar test class used
across all real rule_xml for a customer, with occurrence counts.

Purpose: tells us exactly how many test types actually exist across
real data, and how common each is, BEFORE we design a parser around
guesses. High-frequency test types are worth building deterministic
XML parsers for first; rare ones might not be worth the effort.

Usage:
    uv run python scripts/analyze_test_types.py --name cotecna
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import json
import xml.etree.ElementTree as ET
from collections import Counter

from sqlalchemy import text

from app.db.session import engine


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

        rows = conn.execute(
            text("SELECT object_type, raw_json FROM rules WHERE customer_id = :c"), {"c": customer_id}
        ).fetchall()

    test_counter: Counter[str] = Counter()
    test_counter_by_object_type: dict[str, Counter[str]] = {"RULE": Counter(), "BUILDING_BLOCK": Counter()}
    parse_failures = 0
    rules_with_xml = 0
    total = len(rows)

    for object_type, raw_json in rows:
        data = raw_json if isinstance(raw_json, dict) else json.loads(raw_json)
        rule_xml = data.get("rule_xml")
        if not rule_xml:
            continue
        rules_with_xml += 1
        try:
            root = ET.fromstring(rule_xml)
        except ET.ParseError:
            parse_failures += 1
            continue
        for test_el in root.iter("test"):
            name = test_el.get("name", "UNKNOWN")
            short_name = name.rsplit(".", 1)[-1]  # com.q1labs...ThresholdFunction_Test -> ThresholdFunction_Test
            test_counter[short_name] += 1
            if object_type in test_counter_by_object_type:
                test_counter_by_object_type[object_type][short_name] += 1

    print(f"Total rules/BBs: {total}")
    print(f"Rules with rule_xml present: {rules_with_xml}")
    print(f"XML parse failures: {parse_failures}")
    print(f"\nDistinct test classes found: {len(test_counter)}")
    print(f"Total test occurrences: {sum(test_counter.values())}\n")

    print(f"{'Test Class':<45} {'Total':>8} {'in RULE':>10} {'in BB':>8}")
    print("-" * 73)
    for name, count in test_counter.most_common():
        in_rule = test_counter_by_object_type["RULE"].get(name, 0)
        in_bb = test_counter_by_object_type["BUILDING_BLOCK"].get(name, 0)
        print(f"{name:<45} {count:>8} {in_rule:>10} {in_bb:>8}")


if __name__ == "__main__":
    main()