import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sqlalchemy import text
from app.db.session import engine

with engine.connect() as conn:
    print(conn.execute(text("SELECT max(finished_at) FROM sync_runs WHERE endpoint='rules_with_data'")).scalar())