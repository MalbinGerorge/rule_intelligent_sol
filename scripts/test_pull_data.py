"""
Pull raw responses from all 5 QRadar endpoints for a given customer and
save them to disk under logs/raw_pulls/<customer>/.

This is a TEST/INSPECTION script, not the production ingestion job — its
purpose is to let you look at real payloads and confirm field names
before we write the actual parsing logic (several fields in the schema
are still marked TODO pending exactly this).

Usage:
    uv run python scripts/test_pull_data.py --name cotecna

Prerequisite: the customer must already exist via scripts/push_credentials.py.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine
from app.services.qradar_client import QRadarClient


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
        raise SystemExit(
            f"No customer named '{name}' found (or no credentials saved). "
            f"Run scripts/push_credentials.py first."
        )
    return dict(row)


def save(out_dir: Path, endpoint: str, index: int, content: str, ext: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{endpoint}_{index}.{ext}"
    if ext == "json":
        # QRadar returns JSON minified on one line — pretty-print so the
        # saved file is actually readable (and so "how many rows are in
        # here" is obvious at a glance instead of looking like one row).
        try:
            content = json.dumps(json.loads(content), indent=2)
        except json.JSONDecodeError:
            pass  # save as-is if it's not valid JSON for some reason
    path.write_text(content, encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="customer name, e.g. cotecna")
    args = parser.parse_args()

    customer = load_customer(args.name)
    client = QRadarClient(
        host=customer["qradar_host"],
        token=customer["token"],
        verify_ssl=customer["verify_ssl"],
    )
    print("*"*100)
    print(f"Pulling data for '{args.name}' ({customer['qradar_host']})...\n")
    print(f"token: {customer['token']}")
    print(f"verify_ssl: {customer['verify_ssl']}")
    print("*"*100)


    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path("logs/raw_pulls") / args.name / timestamp

    print(f"Pulling data for '{args.name}' ({customer['qradar_host']}) -> {out_dir}\n")

    jobs = [
        ("rules_with_data", client.fetch_rules_with_data, "json"),
        ("rules_offense_contributions", client.fetch_rules_offense_contributions, "json"),
        ("building_blocks", client.fetch_building_blocks, "json"),
        ("rules", client.fetch_rules, "json"),
    ]

    rules_with_data_pages: list[str] = []
    for endpoint, fetch_fn, ext in jobs:
        try:
            pages = fetch_fn()
        except Exception as exc:  # noqa: BLE001 - this is a debug script, we want to see everything
            print(f"[FAIL] {endpoint}: {exc}")
            continue
        if endpoint == "rules_with_data":
            rules_with_data_pages = pages
        for i, page in enumerate(pages):
            path = save(out_dir, endpoint, i, page, ext)
            print(f"[OK]   {endpoint} page {i}: {len(page)} bytes -> {path}")

    # MITRE mapping is per-rule (keyed by each rule's "identifier"), not
    # one bulk call — so we pull it using the identifiers from
    # rules_with_data, which must have been fetched successfully above.
    identifiers: list[str] = []
    for page in rules_with_data_pages:
        try:
            records = json.loads(page)
        except json.JSONDecodeError:
            continue
        for rule in records if isinstance(records, list) else []:
            identifier = rule.get("identifier", "")
            if identifier:
                identifiers.append(identifier)

    if not identifiers:
        print("[SKIP] mitre_mapping: no rule identifiers found in rules_with_data — nothing to look up.")
    else:
        print(f"\nFetching MITRE coverage for {len(identifiers)} rule identifiers...")
        results = []
        failures = 0
        for identifier in identifiers:
            try:
                print(f"This is the identifier being passed from rules_with_data to the MITRE mapping endpoint: {identifier}")
                print("*"*50)
                results.append({"identifier": identifier, "mitre_coverage": client.fetch_mitre_mapping(identifier)})
            except Exception as exc:  # noqa: BLE001
                failures += 1
                results.append({"identifier": identifier, "error": str(exc)})
        path = save(out_dir, "mitre_mapping", 0, json.dumps(results, indent=2), "json")
        print(f"[OK]   mitre_mapping: {len(identifiers) - failures} succeeded, {failures} failed -> {path}")

    print(f"\nDone. Inspect the files in {out_dir} to confirm real field names,")
    print("then we update the ORM models / parsers to match.")


if __name__ == "__main__":
    main()