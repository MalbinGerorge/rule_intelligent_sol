"""
Manual check: run the MITRE technique gap analysis for one customer,
print the results. Not a production endpoint -- just for verifying
MitreGapAnalyzer's real output against real Postgres/Neo4j data
before wiring it into an API.

Usage:
    uv run python scripts/check_mitre_gaps.py --name cotecna
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.db.session import engine
from app.graph.client import get_driver, close_driver
from app.recommendations.mitre_gap_analyzer import MitreGapAnalyzer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="customer name, e.g. cotecna")
    args = parser.parse_args()

    with engine.connect() as conn:
        customer_id = conn.execute(
            text("SELECT id FROM customers WHERE name = :name"), {"name": args.name}
        ).scalar_one_or_none()
    if customer_id is None:
        raise SystemExit(f"No customer named '{args.name}'.")

    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    driver = get_driver()

    try:
        analyzer = MitreGapAnalyzer(db, driver)
        gaps = analyzer.analyze(customer_id)

        recommendable = [g for g in gaps if g.suggested_rules]
        no_peer = [g for g in gaps if not g.suggested_rules]

        print(f"\n{args.name}: {len(gaps)} total gap(s) against the full MITRE catalog")
        print(f"  {len(recommendable)} recommendable (real peer evidence)")
        print(f"  {len(no_peer)} with no peer coverage yet\n")

        print("=== RECOMMENDABLE GAPS ===")
        for g in recommendable:
            sub = " (sub-technique)" if g.is_subtechnique else ""
            print(f"\n- {g.technique_id}{sub}: {g.technique_name}")
            print(f"  Tactics: {', '.join(g.tactic_names)}")
            print(f"  Peers: {g.peer_customer_names}")
            for s in g.suggested_rules:
                feasible = "OK" if s.customer_has_required_log_source else "BLOCKED (missing log source)"
                print(f"    - [{s.source_customer_name}] {s.title} "
                      f"(level: {s.level}, mitre_source: {s.mitre_source}, confidence: {s.mitre_confidence})")
                print(f"        requires: {s.required_log_source_types or ['unknown']} -> {feasible}")

        print(f"\n=== GAPS WITH NO PEER COVERAGE ({len(no_peer)}) ===")
        for g in no_peer[:20]:
            sub = " (sub-technique)" if g.is_subtechnique else ""
            print(f"  {g.technique_id}{sub}: {g.technique_name} [{', '.join(g.tactic_names)}]")
        if len(no_peer) > 20:
            print(f"  ... and {len(no_peer) - 20} more")

    finally:
        db.close()
        close_driver()


if __name__ == "__main__":
    main()