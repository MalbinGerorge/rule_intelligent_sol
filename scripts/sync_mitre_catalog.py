"""
Syncs the FULL official MITRE ATT&CK Enterprise technique catalog --
NOT customer-scoped, refreshed periodically (MITRE releases a few
times a year), used as the comparison baseline for MitreGapAnalyzer.

Source: MITRE's own official, public STIX 2.1 data
(github.com/mitre-attack/attack-stix-data), parsed via
mitreattack-python -- MITRE's own maintained library for exactly
this task, rather than hand-parsing raw STIX ourselves.

Usage:
    uv run python scripts/sync_mitre_catalog.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from mitreattack.stix20 import MitreAttackData
from sqlalchemy import text

from app.db.session import engine

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


# Confirmed mapping from STIX kill_chain_phases phase_name slugs to the
# REAL, official MITRE ATT&CK Enterprise tactic display names -- built
# from a CONFIRMED real bug: a naive slug.replace("-", " ").title()
# transform produced "Stealth" for T1055.011, when MITRE's own real
# published data (attack.mitre.org) confirms the correct tactic is
# "Defense Evasion". "stealth" is a legacy/internal STIX phase_name
# slug MITRE's data still uses for this tactic -- not reflected by any
# generic string transform. Built explicitly, not trusted blindly,
# since this proves at least one real slug doesn't follow the
# expected hyphen-to-space pattern.
_TACTIC_NAME_BY_PHASE_SLUG = {
    "reconnaissance": "Reconnaissance",
    "resource-development": "Resource Development",
    "initial-access": "Initial Access",
    "execution": "Execution",
    "persistence": "Persistence",
    "privilege-escalation": "Privilege Escalation",
    "defense-evasion": "Defense Evasion",
    "stealth": "Defense Evasion",  # CONFIRMED legacy alias -- see comment above
    "credential-access": "Credential Access",
    "discovery": "Discovery",
    "lateral-movement": "Lateral Movement",
    "collection": "Collection",
    "command-and-control": "Command and Control",
    "exfiltration": "Exfiltration",
    "impact": "Impact",
}


def _extract_tactic_names(technique: dict) -> list[str]:
    names = []
    for phase in technique.get("kill_chain_phases", []):
        if phase.get("kill_chain_name") != "mitre-attack":
            continue
        slug = phase.get("phase_name")
        mapped = _TACTIC_NAME_BY_PHASE_SLUG.get(slug)
        if mapped:
            names.append(mapped)
        else:
            # Genuinely unknown slug -- fall back to the naive
            # transform but don't pretend this is confirmed correct;
            # worth checking manually if this path ever triggers.
            names.append(slug.replace("-", " ").title() if slug else "Unknown")
    return names


def _extract_technique_id(technique: dict) -> str | None:
    for ref in technique.get("external_references", []):
        if ref.get("source_name") == "mitre-attack":
            return ref.get("external_id")
    return None


def main() -> None:
    catalog_path = _download_catalog()
    mitre_attack_data = MitreAttackData(str(catalog_path))

    # remove_revoked_deprecated=True -- CONFIRMED from MITRE's own
    # USAGE.md: revoked/deprecated objects are kept in the raw data for
    # backward compat but are no longer maintained. Comparing coverage
    # against retired techniques would be misleading.
    techniques = mitre_attack_data.get_techniques(remove_revoked_deprecated=True)

    rows = []
    for t in techniques:
        technique_id = _extract_technique_id(t)
        if not technique_id:
            continue
        is_subtechnique = bool(t.get("x_mitre_is_subtechnique", False))
        parent_technique_id = technique_id.split(".")[0] if is_subtechnique and "." in technique_id else None
        rows.append(
            {
                "technique_id": technique_id,
                "technique_name": t.get("name"),
                "tactic_names": _extract_tactic_names(t),
                "is_subtechnique": is_subtechnique,
                "parent_technique_id": parent_technique_id,
            }
        )

    print(f"Parsed {len(rows)} non-revoked, non-deprecated techniques/sub-techniques.")

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE mitre_technique_catalog"))
        for row in rows:
            conn.execute(
                text(
                    """
                    INSERT INTO mitre_technique_catalog
                        (technique_id, technique_name, tactic_names, is_subtechnique, parent_technique_id)
                    VALUES
                        (:technique_id, :technique_name, :tactic_names, :is_subtechnique, :parent_technique_id)
                    """
                ),
                row,
            )

    print(f"Synced {len(rows)} techniques into mitre_technique_catalog.")


if __name__ == "__main__":
    main()