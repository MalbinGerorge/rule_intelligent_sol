"""
Full refresh of custom_event_properties / custom_event_property_expressions
from live QRadar data. DELETE-then-INSERT for one customer's rows, not
incremental modification-date comparison -- see the migration's
docstring for why (not every expression endpoint confirms a
modification_date field; full refresh also correctly handles
deletions on the QRadar side, which incremental comparison alone
would never catch).

Intended to run on a schedule (e.g. twice daily) via
scripts/sync_custom_properties.py -- not called live during an
investigation. This IS structural/schema-like data (how QRadar
extracts a field from a payload), unlike reference set CONTENTS,
which stays deliberately live-only.
"""
from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.qradar_client import QRadarClient

# Maps expression_type -> the QRadarClient method that fetches it
_EXPRESSION_FETCHERS = {
    "regex": "fetch_property_expressions",
    "json": "fetch_property_json_expressions",
    "xml": "fetch_property_xml_expressions",
    "cef": "fetch_property_cef_expressions",
    "leef": "fetch_property_leef_expressions",
    "nvp": "fetch_property_nvp_expressions",
    "aql": "fetch_property_aql_expressions",
}


def _extract_type_specific_data(exp_type: str, expr: dict) -> dict:
    """Only the regex and nvp shapes carry extra fields beyond a
    single "expression" string -- everything else (json/xml/cef/leef/
    aql) is captured by "expression" alone, per the real field docs."""
    if exp_type == "regex":
        return {
            "regex": expr.get("regex"),
            "capture_group": expr.get("capture_group"),
            "format_string": expr.get("format_string"),
        }
    if exp_type == "nvp":
        return {
            "expression": expr.get("expression"),
            "delimiter_pair": expr.get("delimiter_pair"),
            "delimiter_name_value": expr.get("delimiter_name_value"),
        }
    return {"expression": expr.get("expression")}


def sync_custom_event_properties(db: Session, qradar_client: QRadarClient, customer_id: int) -> dict:
    """
    Returns:
        {"properties_synced": int, "builtin_properties_discovered": int,
         "expressions_synced": int, "expressions_skipped_unexpected": int}

    CONFIRMED from real data: AQL-type expressions can reference
    QRadar's own BUILT-IN fields (PACKETS_FROM_SERVER_FACADE ->
    "Packets Received", etc.), which never appear in regex_properties
    (that endpoint only ever lists CUSTOM properties). These are real,
    useful field mappings -- not discarded. When an "aql"-type
    expression's parent identifier doesn't match a known custom
    property, a synthetic property row is created for it
    (is_builtin_field=True), using the expression's own display name.
    Multiple expressions sharing the same builtin parent identifier
    correctly reuse the SAME synthetic row (deduped via
    identifier_to_id), not one row per expression.

    expressions_skipped_unexpected is now reserved for a genuinely
    different, worth-investigating case: a NON-aql expression type
    (regex/json/xml/cef/leef/nvp) with no matching parent -- those
    should always have a real custom property, so a nonzero count
    here would indicate an actual data problem, unlike the expected
    aql/built-in case above.
    """
    property_pages = qradar_client.fetch_regex_properties()
    all_properties = []
    for page in property_pages:
        all_properties.extend(json.loads(page))

    all_expressions: list[tuple[str, dict]] = []
    for exp_type, method_name in _EXPRESSION_FETCHERS.items():
        fetch_method = getattr(qradar_client, method_name)
        pages = fetch_method()
        for page in pages:
            for item in json.loads(page):
                all_expressions.append((exp_type, item))

    # Full refresh: clear this customer's rows first. ON DELETE CASCADE
    # on custom_event_property_expressions.property_id means clearing
    # the parent table alone is sufficient -- no separate DELETE needed
    # for the expressions table.
    db.execute(
        text("DELETE FROM custom_event_properties WHERE customer_id = :c"), {"c": customer_id}
    )

    identifier_to_id: dict[str, int] = {}
    for prop in all_properties:
        result = db.execute(
            text(
                """
                INSERT INTO custom_event_properties
                    (customer_id, qradar_identifier, name, description, property_type,
                     use_for_rule_engine, datetime_format, locale, auto_discovered, username,
                     is_builtin_field)
                VALUES
                    (:customer_id, :qradar_identifier, :name, :description, :property_type,
                     :use_for_rule_engine, :datetime_format, :locale, :auto_discovered, :username,
                     FALSE)
                RETURNING id
                """
            ),
            {
                "customer_id": customer_id,
                "qradar_identifier": prop.get("identifier"),
                "name": prop.get("name"),
                "description": prop.get("description"),
                "property_type": prop.get("property_type"),
                "use_for_rule_engine": prop.get("use_for_rule_engine"),
                "datetime_format": prop.get("datetime_format"),
                "locale": prop.get("locale"),
                "auto_discovered": prop.get("auto_discovered"),
                "username": prop.get("username"),
            },
        )
        identifier_to_id[prop.get("identifier")] = result.scalar_one()

    expressions_inserted = 0
    expressions_skipped_unexpected = 0
    builtin_properties_discovered = 0

    for exp_type, expr in all_expressions:
        parent_identifier = expr.get("regex_property_identifier")
        property_id = identifier_to_id.get(parent_identifier)

        if property_id is None:
            if exp_type == "aql":
                # Newly-discovered BUILT-IN field, not an error -- see
                # docstring. identifier_to_id being updated here means
                # any LATER expression sharing this same parent
                # identifier will correctly reuse this row instead of
                # creating a duplicate.
                builtin_name = expr.get("expression") or parent_identifier
                result = db.execute(
                    text(
                        """
                        INSERT INTO custom_event_properties
                            (customer_id, qradar_identifier, name, is_builtin_field)
                        VALUES (:customer_id, :qradar_identifier, :name, TRUE)
                        RETURNING id
                        """
                    ),
                    {"customer_id": customer_id, "qradar_identifier": parent_identifier, "name": builtin_name},
                )
                property_id = result.scalar_one()
                identifier_to_id[parent_identifier] = property_id
                builtin_properties_discovered += 1
            else:
                expressions_skipped_unexpected += 1
                continue

        db.execute(
            text(
                """
                INSERT INTO custom_event_property_expressions
                    (property_id, qradar_identifier, expression_type, enabled,
                     log_source_type_id, log_source_id, qid, low_level_category_id,
                     type_specific_data)
                VALUES
                    (:property_id, :qradar_identifier, :expression_type, :enabled,
                     :log_source_type_id, :log_source_id, :qid, :low_level_category_id,
                     :type_specific_data)
                """
            ),
            {
                "property_id": property_id,
                "qradar_identifier": expr.get("identifier"),
                "expression_type": exp_type,
                "enabled": expr.get("enabled"),
                "log_source_type_id": expr.get("log_source_type_id"),
                "log_source_id": expr.get("log_source_id"),
                "qid": expr.get("qid"),
                "low_level_category_id": expr.get("low_level_category_id"),
                "type_specific_data": json.dumps(_extract_type_specific_data(exp_type, expr)),
            },
        )
        expressions_inserted += 1

    return {
        "properties_synced": len(all_properties),
        "builtin_properties_discovered": builtin_properties_discovered,
        "expressions_synced": expressions_inserted,
        "expressions_skipped_unexpected": expressions_skipped_unexpected,
    }