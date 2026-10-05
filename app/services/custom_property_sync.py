"""
Full refresh of custom_event_property_expressions from live QRadar
data -- ONE table now, denormalized (property name/type repeated per
expression row) and customer-scoped throughout. DELETE-then-INSERT
per customer, not incremental -- see prior docstring reasoning: not
every expression endpoint confirms a modification_date, and full
refresh correctly handles QRadar-side deletions.

Intended to run on a schedule (e.g. twice daily) via
scripts/sync_custom_properties.py.
"""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.qradar_client import QRadarClient

_EXPRESSION_FETCHERS = {
    "regex": "fetch_property_expressions",
    "json": "fetch_property_json_expressions",
    "xml": "fetch_property_xml_expressions",
    "cef": "fetch_property_cef_expressions",
    "leef": "fetch_property_leef_expressions",
    "nvp": "fetch_property_nvp_expressions",
    "aql": "fetch_property_aql_expressions",
}


def sync_custom_event_properties(
    db: Session, qradar_client: QRadarClient, customer_id: int
) -> dict:
    """
    Returns:
        {"expressions_synced": int, "builtin_properties_discovered": int,
         "expressions_skipped_unexpected": int}
    """
    property_pages = qradar_client.fetch_regex_properties()
    all_properties = []
    for page in property_pages:
        all_properties.extend(json.loads(page))

    # identifier -> {name, property_type, use_for_rule_engine} -- kept
    # in memory only, to denormalize onto each expression row below.
    property_by_identifier = {
        prop.get("identifier"): {
            "name": prop.get("name"),
            "property_type": prop.get("property_type"),
            "use_for_rule_engine": prop.get("use_for_rule_engine"),
        }
        for prop in all_properties
    }

    all_expressions: list[tuple[str, dict]] = []
    for exp_type, method_name in _EXPRESSION_FETCHERS.items():
        fetch_method = getattr(qradar_client, method_name)
        pages = fetch_method()
        for page in pages:
            for item in json.loads(page):
                all_expressions.append((exp_type, item))

    db.execute(
        text("DELETE FROM custom_event_property_expressions WHERE customer_id = :c"),
        {"c": customer_id},
    )

    expressions_inserted = 0
    expressions_skipped_unexpected = 0
    builtin_discovered_identifiers: set[str] = set()

    for exp_type, expr in all_expressions:
        parent_identifier = expr.get("regex_property_identifier")
        known_property = property_by_identifier.get(parent_identifier)

        if known_property is None:
            if exp_type == "aql":
                # Real, confirmed case (see prior version's docstring):
                # AQL expressions can reference QRadar's own BUILT-IN
                # fields, never listed in regex_properties.
                builtin_discovered_identifiers.add(parent_identifier)
                property_name = expr.get("expression") or parent_identifier
                property_type = None
                use_for_rule_engine = None
                is_builtin = True
            else:
                expressions_skipped_unexpected += 1
                continue
        else:
            property_name = known_property["name"]
            property_type = known_property["property_type"]
            use_for_rule_engine = known_property["use_for_rule_engine"]
            is_builtin = False

        type_specific = _flatten_type_specific(exp_type, expr)

        db.execute(
            text(
                """
                INSERT INTO custom_event_property_expressions
                    (customer_id, property_qradar_identifier, property_name, property_type,
                     use_for_rule_engine, is_builtin_field,
                     qradar_identifier, expression_type, enabled,
                     log_source_type_id, log_source_id, qid, low_level_category_id,
                     expression, regex, capture_group, format_string,
                     delimiter_pair, delimiter_name_value)
                VALUES
                    (:customer_id, :property_qradar_identifier, :property_name, :property_type,
                     :use_for_rule_engine, :is_builtin_field,
                     :qradar_identifier, :expression_type, :enabled,
                     :log_source_type_id, :log_source_id, :qid, :low_level_category_id,
                     :expression, :regex, :capture_group, :format_string,
                     :delimiter_pair, :delimiter_name_value)
                """
            ),
            {
                "customer_id": customer_id,
                "property_qradar_identifier": parent_identifier,
                "property_name": property_name,
                "property_type": property_type,
                "use_for_rule_engine": use_for_rule_engine,
                "is_builtin_field": is_builtin,
                "qradar_identifier": expr.get("identifier"),
                "expression_type": exp_type,
                "enabled": expr.get("enabled"),
                "log_source_type_id": expr.get("log_source_type_id"),
                "log_source_id": expr.get("log_source_id"),
                "qid": expr.get("qid"),
                "low_level_category_id": expr.get("low_level_category_id"),
                **type_specific,
            },
        )
        expressions_inserted += 1

    return {
        "expressions_synced": expressions_inserted,
        "builtin_properties_discovered": len(builtin_discovered_identifiers),
        "expressions_skipped_unexpected": expressions_skipped_unexpected,
    }


def _flatten_type_specific(exp_type: str, expr: dict) -> dict:
    """Only regex and nvp carry extra fields beyond a single
    "expression" string -- everything else uses expression alone.
    Unused columns for a given type are explicitly None, not omitted,
    so every INSERT's parameter dict has the same fixed key set."""
    base = {
        "expression": None,
        "regex": None,
        "capture_group": None,
        "format_string": None,
        "delimiter_pair": None,
        "delimiter_name_value": None,
    }
    if exp_type == "regex":
        base["regex"] = expr.get("regex")
        base["capture_group"] = expr.get("capture_group")
        base["format_string"] = expr.get("format_string")
    elif exp_type == "nvp":
        base["expression"] = expr.get("expression")
        base["delimiter_pair"] = expr.get("delimiter_pair")
        base["delimiter_name_value"] = expr.get("delimiter_name_value")
    else:
        base["expression"] = expr.get("expression")
    return base
