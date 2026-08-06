"""
Fetches live data from a customer's QRadar console and pushes it
straight into Postgres — the real ingestion job (vs. test_pull_data.py,
which only saves to disk for inspection).

Usage:
    uv run python scripts/ingest.py --name cotecna

Order: rules must be ingested before offense_contributions and
mitre_mappings, since both resolve their foreign key by looking up an
already-ingested rule. Each step is recorded in sync_runs, individually,
so a partial failure is visible per-endpoint rather than all-or-nothing.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import json
from datetime import datetime, timezone

from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine
from app.services.qradar_client import QRadarClient, QRadarAPIError
from app.services.rule_ingest import upsert_rules, upsert_rules_reference, upsert_building_blocks_reference
from app.services.offense_contribution_ingest import upsert_offense_contributions
from app.services.mitre_mapping_ingest import upsert_mitre_mappings


def load_customer(name: str) -> dict:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT c.id, c.qradar_host, c.verify_ssl,
                       pgp_sym_decrypt(cc.token_encrypted, :key) AS token
                FROM customers c
                JOIN customer_credentials cc ON cc.customer_id = c.id
                WHERE c.name = :name
                """
            ),
            {"name": name, "key": settings.token_encryption_key},
        ).mappings().first()
    if row is None:
        raise SystemExit(f"No customer named '{name}' with saved credentials. Run scripts/push_credentials.py first.")
    return dict(row)


def record_sync_run(engine, customer_id: int, endpoint: str, status: str, records: int, error: str | None = None,
                     started_at: datetime | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO sync_runs (customer_id, endpoint, started_at, finished_at, status, records, error)
                VALUES (:customer_id, :endpoint, :started_at, now(), :status, :records, :error)
                """
            ),
            {
                "customer_id": customer_id,
                "endpoint": endpoint,
                "started_at": started_at or datetime.now(timezone.utc),
                "status": status,
                "records": records,
                "error": error,
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="customer name, e.g. cotecna")
    parser.add_argument(
        "--include-system-rules", action="store_true", default=False,
        help="also attempt MITRE lookup for SYSTEM-* rule identifiers (usually 403s — see test_pull_data.py notes)",
    )
    args = parser.parse_args()

    customer = load_customer(args.name)
    customer_id = customer["id"]
    client = QRadarClient(host=customer["qradar_host"], token=customer["token"], verify_ssl=customer["verify_ssl"])

    # -- rules_with_data -> rules -----------------------------------------
    started = datetime.now(timezone.utc)
    try:
        pages = client.fetch_rules_with_data()
        with engine.begin() as session:
            n = upsert_rules(session, customer_id, pages)
        record_sync_run(engine, customer_id, "rules_with_data", "success", n, started_at=started)
        print(f"[OK] rules_with_data -> rules: {n} upserted")
    except QRadarAPIError as e:
        record_sync_run(engine, customer_id, "rules_with_data", "error", 0, str(e), started_at=started)
        raise SystemExit(f"[FAIL] rules_with_data: {e} — aborting, everything else depends on this")

    # -- /analytics/rules -> rules_reference -------------------------------
    started = datetime.now(timezone.utc)
    try:
        pages = client.fetch_rules()
        with engine.begin() as session:
            n = upsert_rules_reference(session, customer_id, pages)
        record_sync_run(engine, customer_id, "rules", "success", n, started_at=started)
        print(f"[OK] rules -> rules_reference: {n} upserted")
    except QRadarAPIError as e:
        record_sync_run(engine, customer_id, "rules", "error", 0, str(e), started_at=started)
        print(f"[FAIL] rules (reference): {e} — continuing, this only affects validation")

    # -- building_blocks -> building_blocks_reference ------------------------
    started = datetime.now(timezone.utc)
    try:
        pages = client.fetch_building_blocks()
        with engine.begin() as session:
            n = upsert_building_blocks_reference(session, customer_id, pages)
        record_sync_run(engine, customer_id, "building_blocks", "success", n, started_at=started)
        print(f"[OK] building_blocks -> building_blocks_reference: {n} upserted")
    except QRadarAPIError as e:
        record_sync_run(engine, customer_id, "building_blocks", "error", 0, str(e), started_at=started)
        print(f"[FAIL] building_blocks: {e} — continuing, this only affects validation")

    # -- rules_offense_contributions ----------------------------------------
    started = datetime.now(timezone.utc)
    try:
        pages = client.fetch_rules_offense_contributions()
        with engine.begin() as session:
            n, skipped = upsert_offense_contributions(session, customer_id, pages)
        record_sync_run(engine, customer_id, "rules_offense_contributions", "success", n, started_at=started)
        print(f"[OK] rules_offense_contributions: {n} upserted, {skipped} skipped (no matching rule)")
    except QRadarAPIError as e:
        record_sync_run(engine, customer_id, "rules_offense_contributions", "error", 0, str(e), started_at=started)
        print(f"[FAIL] rules_offense_contributions: {e} — continuing")

    # -- MITRE coverage, per rule identifier ---------------------------------
    started = datetime.now(timezone.utc)
    with engine.connect() as conn:
        identifiers = [
            row[0] for row in conn.execute(
                text("SELECT identifier FROM rules WHERE customer_id = :c AND identifier IS NOT NULL"),
                {"c": customer_id},
            ).fetchall()
        ]

    system_count = sum(1 for i in identifiers if i.startswith("SYSTEM-"))
    if not args.include_system_rules and system_count:
        identifiers = [i for i in identifiers if not i.startswith("SYSTEM-")]
        print(f"[SKIP] {system_count} SYSTEM-* identifiers (pass --include-system-rules to attempt them)")

    print(f"Fetching MITRE coverage for {len(identifiers)} rule identifiers...")
    results = []
    fetch_failures = 0
    for identifier in identifiers:
        try:
            results.append({"identifier": identifier, "mitre_coverage": client.fetch_mitre_mapping(identifier)})
        except QRadarAPIError as e:
            fetch_failures += 1
            results.append({"identifier": identifier, "error": str(e)})

    with engine.begin() as session:
        n, skipped = upsert_mitre_mappings(session, customer_id, results)
    status = "success" if fetch_failures == 0 else "partial"
    record_sync_run(engine, customer_id, "mitre_coverage", status, n,
                     f"{fetch_failures} identifier(s) failed to fetch" if fetch_failures else None,
                     started_at=started)
    print(f"[OK] mitre_coverage: {n} rows upserted, {skipped} skipped (no matching rule), "
          f"{fetch_failures} identifier fetch failure(s)")

    print("\nDone. Query rule_summary to see the consolidated result.")


if __name__ == "__main__":
    main()