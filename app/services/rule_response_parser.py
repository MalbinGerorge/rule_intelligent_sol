"""
Parses the <responses>/<limiter> section of rule_xml -- a DIFFERENT
part of the tree from <testDefinitions> (conditions parsed by
rule_condition_parser.py). This is what a rule DOES once its
conditions match: dispatch a new event, create/name an offense, write
to a reference set/map/table, or throttle its own responses.

Confirmed real shapes (see project notes / migration docstring for
full detail):
  <newevent>              -- offense creation/naming, event dispatch
  <referenceDataResponse> -- WRITES to a reference set/map/table
  <limiter>               -- response deduplication/throttling
"""
from __future__ import annotations

import xml.etree.ElementTree as ET


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def extract_rule_response(rule_xml: str | None) -> dict | None:
    """Returns None if rule_xml doesn't parse or has no <responses>
    element at all. Otherwise a dict with up to three optional keys:
    "newevent", "reference_write", "limiter" -- each present only if
    that part of the XML actually exists for this rule."""
    if not rule_xml:
        return None

    try:
        root = ET.fromstring(rule_xml)
    except ET.ParseError:
        return None

    responses = root.find("responses")
    if responses is None:
        return None

    result: dict = {}

    newevent = responses.find("newevent")
    if newevent is not None:
        result["newevent"] = {
            "name": newevent.get("name"),
            "description": newevent.get("description"),
            "severity": _to_int(newevent.get("severity")),
            "credibility": _to_int(newevent.get("credibility")),
            "relevance": _to_int(newevent.get("relevance")),
            "qid": _to_int(newevent.get("qid")),
            "low_level_category": _to_int(newevent.get("lowLevelCategory")),
            "force_offense_creation": newevent.get("forceOffenseCreation") == "true",
            "describe_offense": newevent.get("describeOffense") == "true",
            "override_offense_name": newevent.get("overrideOffenseName") == "true",
            "contribute_offense_name": newevent.get("contributeOffenseName") == "true",
            "offense_mapping": _to_int(newevent.get("offenseMapping")),
        }

    ref_response = responses.find("referenceDataResponse")
    if ref_response is not None:
        write_type = None
        for flag in ("referenceMap", "referenceMapOfSets", "referenceMapOfMaps", "referenceTable"):
            if responses.get(flag) == "true":
                write_type = flag
                break
        result["reference_write"] = {
            "target_name": ref_response.get("name"),
            "key_field": ref_response.get("key1"),
            "filter": ref_response.get("Filter"),
            "write_type": write_type,
        }

    limiter = root.find("limiter")
    if limiter is not None:
        result["limiter"] = {
            "response_count": _to_int(limiter.get("responseCount")),
            "interval_count": _to_int(limiter.get("intervalCount")),
            "interval_type": limiter.get("intervalType"),
            "host_type": limiter.get("hostType"),
        }

    return result if result else None