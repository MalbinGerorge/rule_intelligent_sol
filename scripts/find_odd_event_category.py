import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.db.session import engine

with engine.connect() as conn:
    customer_id = conn.execute(text("SELECT id FROM customers WHERE name='cotecna'")).scalar_one()
    rows = conn.execute(text("""
        SELECT r.name, rc.raw_text, rc.structured_data
        FROM rule_conditions rc JOIN rules r ON r.id = rc.rule_id
        WHERE r.customer_id = :c AND rc.test_class = 'EventCategory_Test'
    """), {"c": customer_id}).mappings().all()

    for row in rows:
        cats = row["structured_data"].get("event_category", {}).get("categories", [])
        odd_ones = [c for c in cats if c.get("low_level") is None]
        if odd_ones:
            print(f"=== Rule: {row['name']} ===")
            print(f"raw_text: {row['raw_text']}")
            print(f"odd entries (no dot): {odd_ones}")
            print()