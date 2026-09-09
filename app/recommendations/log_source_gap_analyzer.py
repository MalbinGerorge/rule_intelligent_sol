"""
Log-source-type gap analysis: finds log source types a customer is
ONBOARDED on (real data flowing in) but has built ZERO rule coverage
for, then recommends real, de-identified Sigma rules from OTHER
customers who ARE covering that same type.

Two genuinely separate data sources, deliberately not conflated:
  - "onboarded" -- get_onboarded_log_source_types() (log_source_lookup.py,
    SHARED with MitreGapAnalyzer to avoid drift), real CONFIGURED
    instances with actual events seen.
  - "covered" -- REQUIRES_LOGSOURCE_TYPE edges in Neo4j, derived from
    real, parsed rule logic (DeviceTypeID_Test conditions).

Confidentiality boundary: peer suggestions return ONLY de-identified
Sigma content (title, description, detection logic, tags) from
rule_yaml_representations -- NEVER raw rule_conditions, reference set
values, or anything read directly from a peer's `rules` table.
"""
from __future__ import annotations

import structlog
from neo4j import Driver
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.recommendations.log_source_lookup import get_onboarded_log_source_types

logger = structlog.get_logger(__name__)


class PeerRuleSuggestion(BaseModel):
    source_customer_name: str
    rule_id: int
    title: str
    description: str | None
    level: str | None
    detection: dict
    tags: list[str]
    mitre_source: str | None = None  # 'confirmed' | 'derived' -- only populated by MitreGapAnalyzer
    mitre_confidence: str | None = None  # only populated when mitre_source == 'derived'
    required_log_source_types: list[str] = []  # the PEER rule's real REQUIRES_LOGSOURCE_TYPE targets
    customer_has_required_log_source: bool = True  # can the RECEIVING customer actually use this? True if unknown (no edges) -- never falsely blocks


class LogSourceGap(BaseModel):
    log_source_type_name: str
    qradar_type_id: int
    peer_customer_names: list[str]
    suggested_rules: list[PeerRuleSuggestion]


class LogSourceGapAnalyzer:
    """ONE public entry point: analyze(). Internal methods each do one
    focused piece -- same class-per-service pattern as SigmaGenerator."""

    def __init__(self, db: Session, driver: Driver):
        self.db = db
        self.driver = driver

    def analyze(self, customer_id: int) -> list[LogSourceGap]:
        logger.info("gap_analysis_started", customer_id=customer_id)

        onboarded = get_onboarded_log_source_types(self.db, customer_id)
        covered_names = self._get_covered_log_source_type_names(customer_id)
        logger.info(
            "gap_analysis_inputs_loaded",
            customer_id=customer_id,
            onboarded_type_count=len(onboarded),
            covered_type_count=len(covered_names),
        )

        gaps: list[LogSourceGap] = []
        real_gaps_without_peer_coverage = 0

        for type_row in onboarded:
            if type_row["name"] in covered_names:
                continue  # already covered -- not a gap

            peer_rule_ids_by_customer = self._find_peer_rule_ids(customer_id, type_row["name"])
            if not peer_rule_ids_by_customer:
                logger.info(
                    "real_gap_no_peer_coverage",
                    customer_id=customer_id,
                    log_source_type=type_row["name"],
                    qradar_type_id=type_row["qradar_type_id"],
                )
                real_gaps_without_peer_coverage += 1
                continue

            suggestions = self._build_suggestions(customer_id, peer_rule_ids_by_customer)
            logger.info(
                "gap_with_recommendations_found",
                customer_id=customer_id,
                log_source_type=type_row["name"],
                peer_customers=list(peer_rule_ids_by_customer.keys()),
                suggestion_count=len(suggestions),
            )
            gaps.append(
                LogSourceGap(
                    log_source_type_name=type_row["name"],
                    qradar_type_id=type_row["qradar_type_id"],
                    peer_customer_names=list(peer_rule_ids_by_customer.keys()),
                    suggested_rules=suggestions,
                )
            )

        logger.info(
            "gap_analysis_completed",
            customer_id=customer_id,
            recommendable_gaps=len(gaps),
            real_gaps_without_peer_coverage=real_gaps_without_peer_coverage,
        )
        return gaps

    def _get_covered_log_source_type_names(self, customer_id: int) -> set[str]:
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (r:Rule {customer_id: $customer_id})-[:REQUIRES_LOGSOURCE_TYPE]->(lst:LogSourceType)
                WHERE NOT r.is_superseded
                RETURN DISTINCT lst.name AS name
                """,
                customer_id=customer_id,
            )
            return {record["name"] for record in result}

    def _find_peer_rule_ids(self, customer_id: int, type_name: str) -> dict[str, list[int]]:
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (r:Rule)-[:REQUIRES_LOGSOURCE_TYPE]->(lst:LogSourceType {name: $type_name})
                WHERE NOT r.is_superseded AND r.customer_id <> $customer_id
                RETURN r.customer_id AS customer_id, r.rule_id AS rule_id
                """,
                type_name=type_name,
                customer_id=customer_id,
            )
            rows = [dict(record) for record in result]

        if not rows:
            return {}

        peer_customer_ids = {r["customer_id"] for r in rows}
        id_to_name = self._resolve_customer_names(peer_customer_ids)

        by_customer: dict[str, list[int]] = {}
        for r in rows:
            name = id_to_name.get(r["customer_id"], f"customer_{r['customer_id']}")
            by_customer.setdefault(name, []).append(r["rule_id"])
        return by_customer

    def _resolve_customer_names(self, customer_ids: set[int]) -> dict[int, str]:
        rows = self.db.execute(
            text("SELECT id, name FROM customers WHERE id = ANY(:ids)"),
            {"ids": list(customer_ids)},
        ).mappings().all()
        return {r["id"]: r["name"] for r in rows}

    def _get_required_log_source_types_for_rules(self, rule_ids: list[int]) -> dict[int, list[str]]:
        """Returns {rule_id: [log_source_type_name, ...]} via each
        rule's REQUIRES_LOGSOURCE_TYPE edges. Multiple edges means
        "needs ANY ONE of these" -- CONFIRMED: DeviceTypeID_Test
        creates one edge per acceptable type, not an AND requirement."""
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

    def _build_suggestions(
        self, receiving_customer_id: int, peer_rule_ids_by_customer: dict[str, list[int]]
    ) -> list[PeerRuleSuggestion]:
        """Pulls ONLY de-identified Sigma content -- never raw
        rule_conditions or reference set values. Each suggestion is
        also checked against the RECEIVING customer's (the one with
        the gap) real onboarded log sources -- a rule is useless to
        recommend if that customer doesn't receive the data it needs."""
        all_rule_ids = [rid for ids in peer_rule_ids_by_customer.values() for rid in ids]
        if not all_rule_ids:
            return []

        rows = self.db.execute(
            text(
                """
                SELECT rule_id, title, description, level, detection, tags
                FROM rule_yaml_representations
                WHERE rule_id = ANY(:rule_ids) AND role IN ('standalone', 'base')
                """
            ),
            {"rule_ids": all_rule_ids},
        ).mappings().all()

        rule_id_to_customer_name = {
            rid: name for name, ids in peer_rule_ids_by_customer.items() for rid in ids
        }

        onboarded_names = {
            row["name"] for row in get_onboarded_log_source_types(self.db, receiving_customer_id)
        }
        required_types_by_rule = self._get_required_log_source_types_for_rules(
            [row["rule_id"] for row in rows]
        )

        suggestions = []
        for row in rows:
            required = required_types_by_rule.get(row["rule_id"], [])
            has_required = True if not required else any(t in onboarded_names for t in required)

            suggestions.append(
                PeerRuleSuggestion(
                    source_customer_name=rule_id_to_customer_name.get(row["rule_id"], "unknown"),
                    rule_id=row["rule_id"],
                    title=row["title"],
                    description=row["description"],
                    level=row["level"],
                    detection=row["detection"],
                    tags=row["tags"] or [],
                    required_log_source_types=required,
                    customer_has_required_log_source=has_required,
                )
            )
        return suggestions