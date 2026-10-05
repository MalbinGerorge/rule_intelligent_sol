"""
Reference Log Retriever -- DETERMINISTIC (no LLM, no reasoning). Given
an AttackStep with a confirmed target_log_source (target_server is
OPTIONAL -- see AttackStep.has_enough_detail), finds a REAL,
currently-configured log source on the target QRadar console and
pulls up to REFERENCE_SAMPLE_LIMIT real, recent events from it.

Matching logic: when target_server IS given, both it and the log
source type must appear in a real log source's name (narrow, host-
specific match). When target_server is None (tenant-wide sources like
Azure AD), matches on the log source TYPE alone.

NEVER fabricates a sample. source='not_found' is an honest, expected
outcome -- not an error. When nothing matches exactly, a broader
search surfaces real PARTIAL matches as available_alternatives.
"""

from __future__ import annotations

import json
import time

import structlog

from app.agent.simulator.schemas import AttackStep, ReferenceLogSample
from app.services.qradar_client import QRadarAPIError, QRadarClient

logger = structlog.get_logger(__name__)

REFERENCE_WINDOW = "LAST 7 DAYS"
REFERENCE_SAMPLE_LIMIT = 2
MAX_ALTERNATIVES = 5


class ReferenceLogRetriever:
    def __init__(self, qradar_client: QRadarClient):
        self.client = qradar_client

    def retrieve(self, step: AttackStep) -> ReferenceLogSample:
        started_at = time.perf_counter()

        if not step.has_enough_detail:
            return ReferenceLogSample(source="not_found")

        all_sources = self._fetch_all_sources()
        matched = self._find_exact_match(all_sources, step.target_log_source, step.target_server)

        if matched is None:
            alternatives = self._find_alternatives(
                all_sources, step.target_log_source, step.target_server
            )
            logger.warning(
                "reference_log_no_match",
                target_log_source=step.target_log_source,
                target_server=step.target_server,
                alternative_count=len(alternatives),
            )
            return ReferenceLogSample(source="not_found", available_alternatives=alternatives)

        events = self._query_sample_events(matched)
        duration_ms = round((time.perf_counter() - started_at) * 1000, 1)

        logger.info(
            "reference_log_retrieved",
            target_log_source=step.target_log_source,
            target_server=step.target_server,
            resolved_log_source_name=matched.get("name"),
            found=len(events) > 0,
            duration_ms=duration_ms,
        )

        if not events:
            return ReferenceLogSample(
                source="not_found",
                log_source_name=matched.get("name"),
                log_source_id=matched.get("id"),
                log_source_type_id=matched.get("type_id"),
            )
        return ReferenceLogSample(
            source="qradar",
            log_source_name=matched.get("name"),
            log_source_id=matched.get("id"),
            log_source_type_id=matched.get("type_id"),
            raw_events=events,
        )

    def _fetch_all_sources(self) -> list[dict]:
        try:
            pages = self.client.fetch_log_sources()
        except QRadarAPIError as exc:
            logger.warning("reference_log_source_fetch_failed", error=str(exc))
            return []

        all_sources: list[dict] = []
        for page_text in pages:
            try:
                all_sources.extend(json.loads(page_text))
            except (json.JSONDecodeError, TypeError):
                continue
        return all_sources

    def _find_exact_match(
        self, sources: list[dict], target_log_source: str, target_server: str | None
    ) -> dict | None:
        """Genuine equality only -- NO guessing, no 'closest' or
        'shortest' heuristic. "GVADEVSQL01" and "GVADEVSQL01_Old" are
        two REAL, different log sources; picking between them by any
        rule other than an exact name match is a guess, and this
        pipeline doesn't guess. If the exact name isn't found, the
        caller shows real alternatives (see _find_alternatives) and
        the analyst picks or supplies the precise name -- never us."""
        target_lower = target_log_source.lower().strip()
        for source in sources:
            name = (source.get("name") or "").lower().strip()
            if name == target_lower:
                return source
        return None

    def _find_alternatives(
        self, sources: list[dict], target_log_source: str, target_server: str | None
    ) -> list[str]:
        log_source_lower = target_log_source.lower()
        server_lower = target_server.lower() if target_server else None

        alternatives = []
        for source in sources:
            name = source.get("name") or ""
            name_lower = name.lower()
            matches_type = log_source_lower in name_lower
            matches_server = server_lower is not None and server_lower in name_lower
            if matches_type or matches_server:
                alternatives.append(name)
            if len(alternatives) >= MAX_ALTERNATIVES:
                break
        return alternatives

    def _query_sample_events(self, log_source: dict) -> list[dict]:
        name_escaped = log_source["name"].replace("'", "''")
        # aql = (
        #     f"SELECT * FROM events WHERE LOGSOURCENAME(logsourceid) = '{name_escaped}' "
        #     f"LIMIT {REFERENCE_SAMPLE_LIMIT} {REFERENCE_WINDOW}"
        # )

        # aql = (
        #             f"SELECT 'payload' AS 'Payload' FROM events WHERE LOGSOURCENAME(logsourceid) = '{name_escaped}' "
        #             f"LIMIT {REFERENCE_SAMPLE_LIMIT} {REFERENCE_WINDOW}"
        #         )

        aql = (
            f"SELECT UTF8(payload) AS Payload FROM events WHERE LOGSOURCENAME(logsourceid) = '{name_escaped}' "
            f"LIMIT {REFERENCE_SAMPLE_LIMIT} {REFERENCE_WINDOW}"
        )

        logger.info("reference_log_aql_generated", log_source_name=log_source.get("name"), aql=aql)

        try:
            results = self.client.run_ariel_search(aql)
        except QRadarAPIError as exc:
            logger.warning(
                "reference_log_query_failed",
                log_source_name=log_source.get("name"),
                aql=aql,
                error=str(exc),
            )
            return []

        events = results.get("events") or results.get("results") or []
        if not events:
            logger.info(
                "reference_log_raw_response_empty",
                raw_response_keys=list(results.keys()),
                raw_response=results,
            )
        return events
