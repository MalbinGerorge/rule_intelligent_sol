"""
DSM Property Extractor -- DETERMINISTIC (no LLM). Turns one raw log
payload into a {property_name: value} dictionary, so downstream
agents reason over clean, named fields instead of parsing raw text.

Two passes:
  1. Generic key=value pass -- splits the payload on tabs and reads
     KEY=VALUE pairs (e.g. EventID=4634). A built-in heuristic for
     WinCollect-style payloads, NOT QRadar's authoritative parse.
  2. Synced DSM expressions -- QRadar's own extraction rules, read
     from custom_event_property_expressions (scoped to this
     customer, and to the payload's log source type / log source).
     If both passes produce the same property name, the QRadar
     expression wins.

Known limits (kept visible via skipped_expression_counts, not hidden):
  - Only 'regex' expressions are applied so far; json/xml/cef/leef/
    nvp/aql are counted as skipped by type.
  - qid / low_level_category_id scoping is NOT evaluated -- the event's
    QID isn't known from the raw payload. A regex just won't match
    text it doesn't apply to, but this can over-apply in rare cases.
  - format_string is ignored; only capture_group is used.
  - QRadar uses Java regex, this uses Python's `re`. Patterns that
    don't compile are skipped and counted ('invalid_regex').
"""

from __future__ import annotations

import re
import time

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.agents.simulator.schemas import (
    ExtractedProperties,
    ExtractedProperty,
    ReferenceLogSample,
)

logger = structlog.get_logger(__name__)

_KEY_PATTERN = re.compile(r"^[A-Za-z_][\w\-\.]*$")
# Column alias the retriever's AQL gives the raw payload ("UTF8(payload) AS Payload").
PAYLOAD_KEY = "Payload"
ANY = -1  # QRadar's "not scoped to a specific value" marker in scoping columns


class DSMPropertyExtractor:
    def __init__(self, db: Session, customer_id: int):
        self.db = db
        self.customer_id = customer_id

    def extract(
        self, payload: str, log_source_type_id: int | None, log_source_id: int | None
    ) -> ExtractedProperties:
        started_at = time.perf_counter()
        skipped: dict[str, int] = {}

        found: dict[str, ExtractedProperty] = {}
        for prop in self._extract_generic_nvp(payload):
            found[prop.name] = prop

        for expr in self._load_applicable_expressions(log_source_type_id, log_source_id):
            if expr["expression_type"] != "regex":
                skipped[expr["expression_type"]] = skipped.get(expr["expression_type"], 0) + 1
                continue
            value = self._apply_regex(expr, payload, skipped)
            if value is not None:
                # QRadar's own expression wins over the generic pass.
                found[expr["property_name"]] = ExtractedProperty(
                    name=expr["property_name"], value=value, method="regex"
                )

        result = ExtractedProperties(
            properties=list(found.values()), skipped_expression_counts=skipped
        )
        logger.info(
            "dsm_properties_extracted",
            customer_id=self.customer_id,
            log_source_type_id=log_source_type_id,
            property_count=len(result.properties),
            regex_count=sum(1 for p in result.properties if p.method == "regex"),
            skipped_expression_counts=skipped,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 1),
        )
        return result

    def extract_from_sample(self, sample: ReferenceLogSample) -> list[ExtractedProperties]:
        """One ExtractedProperties per reference event that has a
        payload, in raw_events order. An event without one is skipped
        with a warning (never silently), so a broken AQL alias is
        easy to spot -- but it also means the result can be SHORTER
        than sample.raw_events."""
        results = []
        for event in sample.raw_events:
            payload = event.get(PAYLOAD_KEY)
            if not payload:
                logger.warning("dsm_extract_event_without_payload", event_keys=list(event.keys()))
                continue
            results.append(self.extract(payload, sample.log_source_type_id, sample.log_source_id))
        return results

    def _extract_generic_nvp(self, payload: str) -> list[ExtractedProperty]:
        properties = []
        for index, segment in enumerate(payload.strip().split("\t")):
            key, sep, value = segment.partition("=")
            if not sep:
                continue
            key = key.strip()
            if index == 0 and " " in key:
                # First segment carries the syslog header ("<13>Sep 26 ... HOST AgentDevice");
                # the real key is the last token.
                key = key.split()[-1]
            if not _KEY_PATTERN.match(key):
                continue
            properties.append(
                ExtractedProperty(name=key, value=value.strip(), method="nvp_generic")
            )
        return properties

    def _load_applicable_expressions(
        self, log_source_type_id: int | None, log_source_id: int | None
    ) -> list[dict]:
        rows = (
            self.db.execute(
                text(
                    """
                SELECT id, property_name, expression_type, regex, capture_group
                FROM custom_event_property_expressions
                WHERE customer_id = :customer_id
                  AND COALESCE(enabled, TRUE) = TRUE
                  AND (log_source_type_id = :type_id OR log_source_type_id = :any)
                  AND (log_source_id = :source_id OR log_source_id = :any)
                ORDER BY id
                """
                ),
                {
                    "customer_id": self.customer_id,
                    "type_id": log_source_type_id if log_source_type_id is not None else ANY,
                    "source_id": log_source_id if log_source_id is not None else ANY,
                    "any": ANY,
                },
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]

    def _apply_regex(self, expr: dict, payload: str, skipped: dict[str, int]) -> str | None:
        try:
            match = re.search(expr["regex"], payload)
        except (re.error, TypeError):
            skipped["invalid_regex"] = skipped.get("invalid_regex", 0) + 1
            return None
        if match is None:
            return None
        group = expr["capture_group"] or 1
        try:
            return match.group(group)
        except IndexError:
            skipped["capture_group_out_of_range"] = skipped.get("capture_group_out_of_range", 0) + 1
            return None
