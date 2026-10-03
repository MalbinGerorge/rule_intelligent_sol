"""
Runs the general condition parser against N real rules from Postgres
and prints the extracted structure — for manual review before we trust
this enough to write into Neo4j.

Usage:
    uv run python scripts/test_parse_sample_rules.py --name cotecna --limit 10
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import json

from sqlalchemy import text

from app.db.session import engine
from app.services.rule_condition_parser import parse_rule_conditions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="customer name, e.g. cotecna")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--object-type", default=None, help="filter to RULE or BUILDING_BLOCK only")
    args = parser.parse_args()

    with engine.connect() as conn:
        customer_id = conn.execute(
            text("SELECT id FROM customers WHERE name = :name"), {"name": args.name}
        ).scalar_one_or_none()
        if customer_id is None:
            raise SystemExit(f"No customer named '{args.name}'.")

        query = "SELECT name, object_type, raw_json FROM rules WHERE customer_id = :c"
        params = {"c": customer_id}
        if args.object_type:
            query += " AND object_type = :ot"
            params["ot"] = args.object_type
        query += " ORDER BY id LIMIT :limit"
        params["limit"] = args.limit

        rows = conn.execute(text(query), params).fetchall()

    for rule_name, object_type, raw_json in rows:
        data = raw_json if isinstance(raw_json, dict) else json.loads(raw_json)
        rule_xml = data.get("rule_xml")

        print(f"{'=' * 70}")
        print(f"RULE: {rule_name}  [{object_type}]")
        print(f"{'=' * 70}")

        conditions = parse_rule_conditions(rule_xml)
        if not conditions:
            print("  (no non-BB-reference conditions found)")
        for c in conditions:
            neg = " [NEGATED]" if c["negated"] else ""
            print(f"  - {c['test_class']}{neg}")
            if "field" in c:
                print(f"      {c['field']} {c['operator']} {c['values']}")
            if "threshold" in c:
                t = c["threshold"]
                print(
                    f"      threshold: {t['count']} times ({t['operator']}), "
                    f"grouped by {t['grouping_field']}, "
                    f"cardinality {t['cardinality_count']} {t['cardinality_field']}, "
                    f"within {t['time_value']} {t['time_unit']}"
                )
            for p in c["parameters"]:
                print(f"      param {p['param_id']}: {p['values']}")
        print()


if __name__ == "__main__":
    main()