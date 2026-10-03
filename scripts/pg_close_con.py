import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.db.session import engine

with engine.connect() as conn:
    # See what's connected first
    rows = conn.execute(text("""
        SELECT pid, usename, application_name, client_addr, state, backend_start
        FROM pg_stat_activity
        WHERE datname = 'rule_intelligent_sol'
        ORDER BY backend_start
    """)).fetchall()

    print(f"Found {len(rows)} connection(s):")
    for r in rows:
        print(f"  pid={r.pid} user={r.usename} app={r.application_name} state={r.state} since={r.backend_start}")

    if not rows:
        sys.exit(0)

    confirm = input("\nTerminate ALL of these except the one this script is using? (yes/no): ")
    if confirm.strip().lower() != "yes":
        print("Aborted.")
        sys.exit(0)

    result = conn.execute(text("""
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE datname = 'rule_intelligent_sol'
          AND pid <> pg_backend_pid()
    """))
    conn.commit()
    print(f"\nTerminated {result.rowcount} connection(s).")