"""
Graph API — thin HTTP layer over Neo4j. No Cypher here (that's
app/services/graph_query.py). Same pattern as app/api/endpoint/rules.py:
endpoint owns HTTP concerns and dict-to-schema conversion, service
layer owns the actual query logic.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from neo4j import Session as Neo4jSession

from app.api.schemas.graph import (
    BuildingBlockDependent,
    FieldSearchResult,
    RuleGraphDetail,
    TechniqueSearchResult,
)
from app.dependencies.graph import get_graph_session
from app.services import graph_query

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/rules/search/by-field", response_model=list[FieldSearchResult])
def search_rules_by_field(
    field: str = Query(..., description="e.g. Command"),
    customer_id: int = Query(...),
    session: Neo4jSession = Depends(get_graph_session),
) -> list[FieldSearchResult]:
    rows = graph_query.get_rules_by_field(session, field, customer_id)
    return [FieldSearchResult(**r) for r in rows]


@router.get("/rules/search/by-technique", response_model=list[TechniqueSearchResult])
def search_rules_by_technique(
    technique_id: str = Query(..., description="e.g. T1078"),
    customer_id: int = Query(...),
    session: Neo4jSession = Depends(get_graph_session),
) -> list[TechniqueSearchResult]:
    rows = graph_query.get_rules_by_technique(session, technique_id, customer_id)
    return [TechniqueSearchResult(**r) for r in rows]


@router.get("/building-blocks/{identifier}/dependents", response_model=list[BuildingBlockDependent])
def get_bb_dependents(
    identifier: str,
    customer_id: int = Query(...),
    session: Neo4jSession = Depends(get_graph_session),
) -> list[BuildingBlockDependent]:
    rows = graph_query.get_bb_dependents(session, identifier, customer_id)
    return [BuildingBlockDependent(**r) for r in rows]


@router.get("/rules/{rule_id}", response_model=RuleGraphDetail)
def get_rule_graph(
    rule_id: int,
    session: Neo4jSession = Depends(get_graph_session),
) -> RuleGraphDetail:
    # NOTE: /rules/search/... routes are registered ABOVE this — same
    # "specific path before wildcard" rule we learned the hard way on
    # the Postgres /rules/metrics route. "search" would otherwise try
    # to parse as an int rule_id and 422.
    rule = graph_query.get_rule_node(session, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found in graph")

    return RuleGraphDetail(
        rule=rule,
        references=graph_query.get_rule_references(session, rule_id),
        conditions=graph_query.get_rule_conditions(session, rule_id),
        log_sources=graph_query.get_rule_logsources(session, rule_id),
        mitre=graph_query.get_rule_mitre(session, rule_id),
        followed_by=graph_query.get_rule_followed_by(session, rule_id),
    )