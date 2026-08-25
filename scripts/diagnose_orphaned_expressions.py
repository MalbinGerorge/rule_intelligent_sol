# scripts/diagnose_orphaned_expressions.py
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sqlalchemy import text
from app.db.session import engine
from app.services.qradar_client_factory import build_qradar_client_for_customer
from app.services.custom_property_sync import _EXPRESSION_FETCHERS

CUSTOMER_NAME = "cotecna"

with engine.connect() as db:
    customer_id = db.execute(text("SELECT id FROM customers WHERE name = :n"), {"n": CUSTOMER_NAME}).scalar_one()
    client = build_qradar_client_for_customer(db, customer_id)

    property_pages = client.fetch_regex_properties()
    all_properties = []
    for page in property_pages:
        all_properties.extend(json.loads(page))
    known_identifiers = {p["identifier"] for p in all_properties}
    print(f"Total known properties: {len(known_identifiers)}")

    orphans = []
    for exp_type, method_name in _EXPRESSION_FETCHERS.items():
        pages = getattr(client, method_name)()
        for page in pages:
            for item in json.loads(page):
                pid = item.get("regex_property_identifier")
                if pid not in known_identifiers:
                    orphans.append((exp_type, pid, item.get("identifier"), item.get("expression") or item.get("regex")))

    print(f"\nTotal orphaned expressions: {len(orphans)}")
    print("\nFirst 15 orphans (type, missing_parent_identifier, expression_id, expression_snippet):")
    for o in orphans[:15]:
        print(f"  {o[0]:6s} | parent={o[1]} | expr_id={o[2]} | {str(o[3])[:60]}")