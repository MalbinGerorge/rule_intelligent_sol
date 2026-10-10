"""
Syncs the MITRE ATT&CK Enterprise catalog (tactics + techniques, including
revoked and deprecated ones) -- NOT customer-scoped, refreshed periodically
(MITRE releases a few times a year), used as the comparison baseline for
MitreGapAnalyzer and the simulator's MITRE validator.

Source: MITRE's own official, public STIX 2.1 data
(github.com/mitre-attack/attack-stix-data). Parsing and writing live in
app/ingestion/jobs/mitre_catalog_sync.py.

Usage:
    uv run python scripts/sync_mitre_catalog.py                 # download, then sync
    uv run python scripts/sync_mitre_catalog.py --file <path>   # use a local bundle
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from app.db.session import engine  # noqa: E402
from app.ingestion.jobs.mitre_catalog_sync import sync_mitre_catalog  # noqa: E402

ENTERPRISE_ATTACK_URL = "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/enterprise-attack/enterprise-attack.json"
LOCAL_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "enterprise-attack.json"


def _download_catalog() -> Path:
    LOCAL_CACHE_PATH.parent.mkdir(exist_ok=True)
    print(f"Downloading MITRE ATT&CK Enterprise catalog from {ENTERPRISE_ATTACK_URL} ...")
    resp = requests.get(ENTERPRISE_ATTACK_URL, timeout=120)
    resp.raise_for_status()
    LOCAL_CACHE_PATH.write_bytes(resp.content)
    print(f"Saved to {LOCAL_CACHE_PATH} ({len(resp.content) / 1_000_000:.1f} MB)")
    return LOCAL_CACHE_PATH


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync the MITRE ATT&CK catalog")
    parser.add_argument(
        "--file", type=Path, help="use this local enterprise-attack.json instead of downloading"
    )
    args = parser.parse_args()

    bundle_path = args.file or _download_catalog()
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    counts = sync_mitre_catalog(engine, bundle)
    print(
        f"Synced {counts['tactics']} tactics and "
        f"{counts['active'] + counts['deprecated'] + counts['revoked']} techniques "
        f"({counts['active']} active, {counts['revoked']} revoked "
        f"[{counts['revoked_with_replacement']} with a replacement], {counts['deprecated']} deprecated)."
    )


if __name__ == "__main__":
    main()
