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
import requests, urllib3
urllib3.disable_warnings()

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
    headers={
            "SEC": "04573cf1-1c6d-4f51-867a-96e0d9bfe969",
            "Accept": "application/json",
            "Allow-Hidden": "true",
        }
    # Test 1
    r = requests.get(
        f"{client.host}/api/analytics/rules_with_data",
        headers=headers,
        verify=False,
    )
    print("rules_with_data:", r.status_code)

    # Test 2
    r = requests.get(
        f"{customer['qradar_host']}/console/plugins/app_proxy:UseCaseManager_Service/api/mitre/mitre_coverage/SYSTEM-1443",
        headers=headers,
        verify=False,
    )
    print("mitre:", r.status_code)
    print(r.text)


if __name__ == "__main__":
    main()