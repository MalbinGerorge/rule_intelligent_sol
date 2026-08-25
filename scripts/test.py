import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sqlalchemy import text
from app.db.session import engine

with engine.connect() as conn:
    row = conn.execute(text(
        "SELECT id, customer_id, name FROM rules WHERE name ILIKE '%High Privileged User Locked Out%'"
    )).fetchone()
    print(row)