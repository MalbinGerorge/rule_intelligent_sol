import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.db.session import engine

with engine.connect() as conn:
    rows = conn.execute(text("""
        SELECT name, qradar_rule_id, identifier, linked_rule_identifier
        FROM rules
        WHERE customer_id = (SELECT id FROM customers WHERE name='cotecna')
          AND object_type = 'RULE' AND enabled = true
          AND name = 'Excessive Firewall Denies from Remote Host'
        ORDER BY qradar_rule_id
    """)).fetchall()
    for r in rows:
        print(r)