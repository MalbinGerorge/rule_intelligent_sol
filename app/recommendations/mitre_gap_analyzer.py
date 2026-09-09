"""
MITRE technique gap analysis -- compares a customer's ACTUAL technique
coverage (rule_mitre_unified: confirmed QRadar mappings + LLM-inferred
ones) against the FULL official MITRE ATT&CK catalog
(mitre_technique_catalog), then checks whether any OTHER customer has
real coverage for each gap.

UNSUPPRESSED BY DESIGN: every gap against the full catalog is
returned, even with zero peer coverage -- suggested_rules is simply
empty in that case.

Every suggestion is ALSO checked against the RECEIVING customer's
real onboarded log sources (via log_source_lookup.py, shared with
LogSourceGapAnalyzer) -- a peer's rule is not genuinely useful to
recommend if this customer doesn't receive the log data it needs.

Both 'confirmed' (QRadar-verified) and 'derived' (LLM-inferred) peer
mappings count as real evidence -- mitre_source/mitre_confidence are
always surfaced on each suggestion, never silently merged.

Confidentiality boundary: SAME as LogSourceGapAnalyzer -- peer
suggestions return ONLY de-identified Sigma content, never raw rule
logic.
"""
from __future__ import annotations

import structlog
from neo4j import Driver
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.recommendations.log_source_gap_analyzer import PeerRuleSuggestion
from app.recommendations.log_source_lookup import get_onboarded_log_source_types

logger = structlog.get_logger(__name__)


class MitreGap(BaseModel):
    technique_id: str
    technique_name: str | None
    tactic_names: list[str]
    is_subtechnique: bool
    peer_customer_names: list[str]
    suggested_rules: list[PeerRuleSuggestion]


class MitreGapAnalyzer:
    """ONE public entry point: analyze(). Same class-per-service
    pattern as SigmaGenerator / LogSourceGapAnalyzer."""

    def __init__(self, db: Session, driver: Driver):
        self.db = db
        self.driver = driver

    def analyze(self, customer_id: int) -> list[MitreGap]:
        logger.info("mitre_gap_analysis_started", customer_id=customer_id)

        catalog = self._get_full_catalog()
        covered_ids = self._get_covered_technique_ids(customer_id)
        onboarded_names = {row["name"] for row in get_onboarded_log_source_types(self.db, customer_id)}
        logger.info(
            "mitre_gap_analysis_inputs_loaded",
            customer_id=customer_id,
            catalog_size=len(catalog),
            covered_count=len(covered_ids),
        )

        gaps: list[MitreGap] = []
        gaps_with_peer_count = 0

        for entry in catalog:
            if entry["technique_id"] in covered_ids:
                continue  # already covered -- not a gap

            peer_matches = self._find_peer_rule_matches(customer_id, entry["technique_id"])
            suggestions = self._build_suggestions(peer_matches, onboarded_names)
            peer_customer_names = sorted({m["customer_name"] for m in peer_matches})

            if peer_matches:
                gaps_with_peer_count += 1

            gaps.append(
                MitreGap(
                    technique_id=entry["technique_id"],
                    technique_name=entry["technique_name"],
                    tactic_names=entry["tactic_names"] or [],
                    is_subtechnique=entry["is_subtechnique"],
                    peer_customer_names=peer_customer_names,
                    suggested_rules=suggestions,
                )
            )

        logger.info(
            "mitre_gap_analysis_completed",
            customer_id=customer_id,
            total_gaps=len(gaps),
            gaps_with_peer_recommendations=gaps_with_peer_count,
            gaps_with_no_peer_coverage=len(gaps) - gaps_with_peer_count,
        )
        return gaps

    def _get_full_catalog(self) -> list[dict]:
        rows = self.db.execute(
            text(
                "SELECT technique_id, technique_name, tactic_names, is_subtechnique FROM mitre_technique_catalog"
            )
        ).mappings().all()
        return [dict(r) for r in rows]

    def _get_covered_technique_ids(self, customer_id: int) -> set[str]:
        rows = self.db.execute(
            text(
                "SELECT DISTINCT technique_id FROM rule_mitre_unified "
                "WHERE customer_id = :customer_id AND technique_id IS NOT NULL"
            ),
            {"customer_id": customer_id},
        ).fetchall()
        return {r[0] for r in rows}

    def _find_peer_rule_matches(self, customer_id: int, technique_id: str) -> list[dict]:
        rows = self.db.execute(
            text(
                """
                SELECT rmu.rule_id, c.name AS customer_name, rmu.mitre_source, rmu.confidence
                FROM rule_mitre_unified rmu
                JOIN customers c ON c.id = rmu.customer_id
                WHERE rmu.technique_id = :technique_id AND rmu.customer_id <> :customer_id
                """
            ),
            {"technique_id": technique_id, "customer_id": customer_id},
        ).mappings().all()
        return [dict(r) for r in rows]

    def _get_required_log_source_types_for_rules(self, rule_ids: list[int]) -> dict[int, list[str]]:
        if not rule_ids:
            return {}
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (r:Rule)-[:REQUIRES_LOGSOURCE_TYPE]->(lst:LogSourceType)
                WHERE r.rule_id IN $rule_ids
                RETURN r.rule_id AS rule_id, collect(lst.name) AS log_source_types
                """,
                rule_ids=rule_ids,
            )
            return {record["rule_id"]: record["log_source_types"] for record in result}

    def _build_suggestions(self, peer_matches: list[dict], onboarded_names: set[str]) -> list[PeerRuleSuggestion]:
        """Pulls ONLY de-identified Sigma content. Each suggestion is
        checked against onboarded_names (the RECEIVING customer's real
        log sources) -- an empty required_log_source_types means
        genuinely unknown (no edges found), which defaults to True
        rather than falsely blocking the suggestion."""
        if not peer_matches:
            return []

        rule_ids = [m["rule_id"] for m in peer_matches]
        match_by_rule_id = {m["rule_id"]: m for m in peer_matches}

        rows = self.db.execute(
            text(
                """
                SELECT rule_id, title, description, level, detection, tags
                FROM rule_yaml_representations
                WHERE rule_id = ANY(:rule_ids) AND role IN ('standalone', 'base')
                """
            ),
            {"rule_ids": rule_ids},
        ).mappings().all()

        required_types_by_rule = self._get_required_log_source_types_for_rules(rule_ids)

        suggestions = []
        for row in rows:
            match = match_by_rule_id.get(row["rule_id"])
            required = required_types_by_rule.get(row["rule_id"], [])
            has_required = True if not required else any(t in onboarded_names for t in required)

            suggestions.append(
                PeerRuleSuggestion(
                    source_customer_name=match["customer_name"] if match else "unknown",
                    rule_id=row["rule_id"],
                    title=row["title"],
                    description=row["description"],
                    level=row["level"],
                    detection=row["detection"],
                    tags=row["tags"] or [],
                    mitre_source=match["mitre_source"] if match else None,
                    mitre_confidence=match["confidence"] if match else None,
                    required_log_source_types=required,
                    customer_has_required_log_source=has_required,
                )
            )
        return suggestions