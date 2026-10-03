import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.db.session import engine
from app.services.qradar_client_factory import build_qradar_client_for_customer

CUSTOMER_NAME = "cotecna"

# Search terms -- substrings, not exact names, since the rule's display
# text likely appends namespace/entry_type info that isn't part of the
# real stored "name" field.
# SEARCH_TERMS = [
#     "Schema Admins",
#     "High Permissions Users",
#     "Domain Admins (AFRICA)",
#     "Domain Admins (AMERICA)",
#     "Domain Admins (ASIA)",
#     "Domain Admins (COTECNA.LOC)",
#     "Domain Admins (EUROPE)",
# ]

SEARCH_TERMS = [
    "Active Directory - Schema Admins - Group List",
    "[CyberProof] - High Permissions Users",
    "[CyberProof] - [Cotecna] - Domain Admins (AFRICA)",
    "[CyberProof] - [Cotecna] - Domain Admins (AMERICA)",
    "[CyberProof] - [Cotecna] - Domain Admins (ASIA)",
    "[CyberProof] - [Cotecna] - Domain Admins (COTECNA.LOC)",
    "[CyberProof] - [Cotecna] - Domain Admins (EUROPE)"
]


with engine.connect() as db:
    customer_id = db.execute(
        text("SELECT id FROM customers WHERE name = :name"), {"name": CUSTOMER_NAME}
    ).scalar_one()
    client = build_qradar_client_for_customer(db, customer_id)

import json
pages = client.fetch_reference_sets()
all_sets = []
for page in pages:
    all_sets.extend(json.loads(page))

print(f"Total reference sets on console: {len(all_sets)}\n")

for term in SEARCH_TERMS:
    matches = [s for s in all_sets if term.lower() in s.get("name", "").lower()]
    print(f"=== Search: \"{term}\" ===")
    if not matches:
        print("  NO MATCHING SET FOUND on the live console.")
    for s in matches:
        entries = s.get("number_of_entries", 0)
        flag = "  *** EMPTY ***" if entries == 0 else ""
        print(f"  \"{s['name']}\" | entries={entries} | namespace={s.get('namespace')} | type={s.get('entry_type')}{flag}")
    print()