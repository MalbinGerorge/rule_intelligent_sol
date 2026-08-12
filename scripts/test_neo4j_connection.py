"""
Verifies Neo4j is reachable and can actually read/write — run this
right after `docker compose up -d` to confirm the container is working
before building anything on top of it.

Usage:
    uv run python scripts/test_neo4j_connection.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.graph.client import get_driver, close_driver


def main() -> None:
    driver = get_driver()

    print("1. Verifying connectivity...")
    driver.verify_connectivity()
    print("   OK — connected to Neo4j")

    print("\n2. Writing a test node...")
    with driver.session() as session:
        session.run(
            "MERGE (t:ConnectionTest {id: 'startup-check'}) SET t.checked_at = datetime()"
        )
    print("   OK — write succeeded")

    print("\n3. Reading it back...")
    with driver.session() as session:
        result = session.run("MATCH (t:ConnectionTest {id: 'startup-check'}) RETURN t.checked_at AS checked_at")
        record = result.single()
        print(f"   OK — read succeeded, checked_at = {record['checked_at']}")

    print("\n4. Cleaning up test node...")
    with driver.session() as session:
        session.run("MATCH (t:ConnectionTest {id: 'startup-check'}) DELETE t")
    print("   OK — cleanup succeeded")

    close_driver()
    print("\nAll checks passed — Neo4j is reachable and working correctly.")


if __name__ == "__main__":
    main()