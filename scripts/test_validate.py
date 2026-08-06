"""
Cross-check the rules pulled via rules_with_data against the ground-truth
/analytics/rules endpoint, using the most recent files saved by
test_pull_data.py.

This is a TEST script — it prints a pass/fail summary to the terminal
rather than writing to validation_results yet, since the exact field
names for rule IDs in both payloads are still unconfirmed. It tries a
few common field-name guesses and tells you clearly which one worked
(or if none did), so we know exactly what to hardcode once confirmed.

Usage:
    uv run python scripts/test_validate.py --name cotecna
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

RULE_ID_XML_CANDIDATES = ["id", "ruleId", "rule_id"]
RULE_ID_JSON_CANDIDATES = ["id", "ruleId", "rule_id"]
BB_ID_JSON_CANDIDATES = ["id", "bbId", "bb_id"]


def latest_pull_dir(customer: str) -> Path:
    base = Path("logs/raw_pulls") / customer
    if not base.exists():
        raise SystemExit(f"No pulls found for '{customer}'. Run scripts/test_pull_data.py first.")
    runs = sorted(base.iterdir())
    if not runs:
        raise SystemExit(f"'{base}' exists but is empty.")
    return runs[-1]


def extract_rule_ids_from_xml(pages: list[str]) -> tuple[set[str], str | None]:
    """Best-effort: try each candidate attribute name on every <rule>
    element until one actually yields IDs. Returns (ids, field_used)."""
    for field in RULE_ID_XML_CANDIDATES:
        ids = set()
        for page in pages:
            try:
                root = ET.fromstring(page)
            except ET.ParseError:
                continue
            for rule_el in root.iter("rule"):
                val = rule_el.get(field)
                if val:
                    ids.add(val)
        if ids:
            return ids, field
    return set(), None


def extract_ids_from_json(pages: list[str], candidates: list[str]) -> tuple[set[str], str | None]:
    for field in candidates:
        ids = set()
        for page in pages:
            try:
                data = json.loads(page)
            except json.JSONDecodeError:
                continue
            records = data if isinstance(data, list) else data.get("results", data.get("data", []))
            for rec in records if isinstance(records, list) else []:
                if isinstance(rec, dict) and field in rec:
                    ids.add(str(rec[field]))
        if ids:
            return ids, field
    return set(), None


def read_pages(pull_dir: Path, endpoint: str) -> list[str]:
    return [p.read_text(encoding="utf-8") for p in sorted(pull_dir.glob(f"{endpoint}_*"))]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="customer name, e.g. cotecna")
    args = parser.parse_args()

    pull_dir = latest_pull_dir(args.name)
    print(f"Validating against pull: {pull_dir}\n")

    # --- Rules pipeline ---
    ingested_pages = read_pages(pull_dir, "rules_with_data")
    reference_pages = read_pages(pull_dir, "rules")

    ingested_ids, ingested_field = extract_rule_ids_from_xml(ingested_pages)
    reference_ids, reference_field = extract_ids_from_json(reference_pages, RULE_ID_JSON_CANDIDATES)

    print("=== Rules ===")
    if ingested_field:
        print(f"rules_with_data: found {len(ingested_ids)} rule IDs using attribute '{ingested_field}'")
    else:
        print("rules_with_data: could NOT find rule IDs with any candidate attribute "
              f"{RULE_ID_XML_CANDIDATES} — open the saved XML and tell me the real attribute name.")

    if reference_field:
        print(f"/analytics/rules: found {len(reference_ids)} rule IDs using field '{reference_field}'")
    else:
        print("/analytics/rules: could NOT find rule IDs with any candidate field "
              f"{RULE_ID_JSON_CANDIDATES} — open the saved JSON and tell me the real field name.")

    if ingested_ids and reference_ids:
        missing_in_reference = ingested_ids - reference_ids
        missing_in_ingested = reference_ids - ingested_ids
        print(f"\nPASS: {len(ingested_ids & reference_ids)} rules matched in both.")
        if missing_in_reference:
            print(f"FAIL: {len(missing_in_reference)} rules in rules_with_data but NOT in /analytics/rules: "
                  f"{sorted(missing_in_reference)[:10]}{' ...' if len(missing_in_reference) > 10 else ''}")
        if missing_in_ingested:
            print(f"NOTE: {len(missing_in_ingested)} rules in /analytics/rules but not pulled via rules_with_data "
                  f"(may be disabled/filtered): {sorted(missing_in_ingested)[:10]}"
                  f"{' ...' if len(missing_in_ingested) > 10 else ''}")

    # --- Building blocks reference (printed for manual inspection) ---
    bb_pages = read_pages(pull_dir, "building_blocks")
    bb_ids, bb_field = extract_ids_from_json(bb_pages, BB_ID_JSON_CANDIDATES)
    print("\n=== Building Blocks (reference only) ===")
    if bb_field:
        print(f"/analytics/building_blocks: found {len(bb_ids)} BB IDs using field '{bb_field}'")
        print(f"Sample: {sorted(bb_ids)[:10]}")
    else:
        print("Could not find BB IDs with any candidate field — open the saved JSON to confirm.")
    print(
        "\nTODO: building-block validation against rules (rule_building_blocks table) is "
        "still pending — we need to see how a rule's XML actually references a BB "
        "(by ID, by name, or embedded some other way) before we can extract and compare."
    )


if __name__ == "__main__":
    main()