import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.db.session import engine

with engine.connect() as conn:
    rows = conn.execute(text("""
        SELECT name, count(*) FROM rules
        WHERE customer_id = (SELECT id FROM customers WHERE name='cotecna')
          AND object_type = 'BUILDING_BLOCK'
        GROUP BY name HAVING count(*) > 1
    """)).fetchall()
    for r in rows:
        print(r)
    print(f"Total duplicate names: {len(rows)}")