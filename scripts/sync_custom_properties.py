"""
Full refresh of custom event property / DSM extraction data for one
customer. Intended to run on a schedule (e.g. twice daily) -- not
called live during an investigation, since this is structural/schema-
like data (how QRadar extracts fields from a payload), not fast-
changing operational data.

Usage:
    uv run python scripts/sync_custom_properties.py --name cotecna
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

from sqlalchemy import text

from app.db.session import engine
from app.services.custom_property_sync import sync_custom_event_properties
from app.services.qradar_client_factory import build_qradar_client_for_customer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="customer name, e.g. cotecna")
    args = parser.parse_args()

    with engine.begin() as db:
        customer_id = db.execute(
            text("SELECT id FROM customers WHERE name = :name"), {"name": args.name}
        ).scalar_one_or_none()
        if customer_id is None:
            raise SystemExit(f"No customer named '{args.name}'.")

        qradar_client = build_qradar_client_for_customer(db, customer_id)
        result = sync_custom_event_properties(db, qradar_client, customer_id)

    print(f"Properties synced:               {result['properties_synced']}")
    print(f"Builtin fields discovered:       {result['builtin_properties_discovered']}")
    print(f"Expressions synced:              {result['expressions_synced']}")
    print(f"Expressions skipped (unexpected): {result['expressions_skipped_unexpected']}")


if __name__ == "__main__":
    main()