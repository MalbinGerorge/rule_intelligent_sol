"""
Builds the Neo4j graph for one customer from Postgres data.

Usage:
    uv run python scripts/build_graph.py --name cotecna
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

from sqlalchemy import text

from app.db.session import engine
from app.graph.client import get_driver, close_driver
from app.graph.loader import build_customer_graph


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

    driver = get_driver()
    with engine.connect() as db:
        result = build_customer_graph(driver, db, customer_id)
    close_driver()

    print(f"Rule/BB nodes:        {result['rule_nodes']}")
    print(f"REFERENCES edges:     {result['reference_edges']}")
    print(f"Condition nodes:      {result['condition_nodes']}")
    print(f"LogSourceType edges:  {result['logsource_type_edges']}")
    print(f"Device edges:         {result['device_edges']}")
    print(f"FOLLOWED_BY edges:    {result['followed_by_edges']}")
    print(f"MITRE edges:          {result['mitre_edges']}")
    print(f"EventCategory edges:  {result['event_category_edges']}")
    print(f"QID edges:            {result['qid_edges']}")
    print(f"ReferenceSet edges:   {result['refset_edges']}")
    print(f"ReferenceMap edges:   {result['refmap_edges']}")


if __name__ == "__main__":
    main()