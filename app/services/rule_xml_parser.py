"""
Extracts BB references from a rule's raw_xml — deterministic XML
parsing, no LLM. See project notes: rule_xml already contains BB
identifiers as literal <userSelection> values, so there's nothing to
infer from natural language here.

CONFIRMED pattern from real QRadar data: a <userSelection> value is a
BB/rule reference only when its parent <parameter>'s <userOptions>
has a method whose name contains "Rules" (e.g. getEventRules,
getCommonRules, getFlowRules) — this is QRadar's own naming
convention for "populate a rule/BB picker list" parameters. Verified
against real samples: getEventRules/getCommonRules parameters DO
match; getDevices (a device picker, unrelated to BB refs) does NOT.

userSelection can be a single identifier or a comma-separated list
(seen in real data: "SYSTEM-1202, SYSTEM-1179").
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

log = logging.getLogger("rule_xml_parser")


def extract_bb_references(rule_xml: str | None) -> list[dict]:
    """
    Returns a list of {"bb_identifier": str, "raw_xml_snippet": str}
    — one entry per referenced BB/rule identifier found. Deduplicates
    identical (identifier, snippet) pairs is NOT done here — caller
    dedupes if needed, since duplicate refs across different tests are
    still meaningful (a rule can reference the same BB twice, once per
    condition).
    """
    if not rule_xml:
        return []

    try:
        root = ET.fromstring(rule_xml)
    except ET.ParseError as e:
        log.warning("Failed to parse rule_xml: %s", e)
        return []

    results: list[dict] = []

    for test_el in root.iter("test"):
        for param_el in test_el.findall("parameter"):
            user_options = param_el.find("userOptions")
            if user_options is None:
                continue

            method = user_options.get("method", "")
            if "Rules" not in method:
                continue  # not a rule/BB-selector parameter

            user_selection = param_el.find("userSelection")
            if user_selection is None or not user_selection.text:
                continue

            snippet = ET.tostring(param_el, encoding="unicode")

            for identifier in user_selection.text.split(","):
                identifier = identifier.strip()
                if identifier:
                    results.append({"bb_identifier": identifier, "raw_xml_snippet": snippet})

    return results