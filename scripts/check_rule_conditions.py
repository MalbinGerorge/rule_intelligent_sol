import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.db.session import engine

with engine.connect() as conn:
    print("--- columns ---")
    cols = conn.execute(text("""
        SELECT column_name, data_type FROM information_schema.columns
        WHERE table_name = 'rule_conditions' ORDER BY ordinal_position
    """)).fetchall()
    for c in cols:
        print(c)

    print("\n--- first 10 rows ---")
    rows = conn.execute(text("SELECT * FROM rule_conditions LIMIT 10")).fetchall()
    for r in rows:
        print(r)