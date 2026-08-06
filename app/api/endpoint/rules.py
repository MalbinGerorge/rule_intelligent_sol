"""Rules API — thin HTTP layer. No SQL here (that's app/services/rule_query.py).
Converts service-layer dicts into API schemas (app/api/schemas/rule.py) —
that conversion happens here, not in the service layer."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.schemas.rule import RuleHealthMetrics, RuleListResponse, RuleSummary
from app.dependencies.db import get_db
from app.services import rule_query

router = APIRouter(prefix="/rules", tags=["rules"])


@router.get("", response_model=RuleListResponse)
def list_rules(
    db: Session = Depends(get_db),
    customer_id: int = Query(..., description="Filter to one customer"),
    object_type: str | None = Query(None, description="RULE or BUILDING_BLOCK"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
) -> RuleListResponse:
    rows = rule_query.list_rules(db, customer_id, object_type, limit, offset)
    rules = [RuleSummary.model_validate(row) for row in rows]
    return RuleListResponse(count=len(rules), results=rules)


@router.get("/metrics", response_model=RuleHealthMetrics)
def get_health_metrics(
    db: Session = Depends(get_db),
    customer_id: int = Query(..., description="Filter to one customer"),
) -> RuleHealthMetrics:
    # NOTE: this route must stay defined ABOVE /{rule_id} below — FastAPI
    # matches routes in registration order, and "/metrics" would otherwise
    # get swallowed by the /{rule_id} path parameter.
    metrics = rule_query.get_health_metrics(db, customer_id)
    return RuleHealthMetrics.model_validate(metrics)


@router.get("/{rule_id}", response_model=RuleSummary)
def get_rule(rule_id: int, db: Session = Depends(get_db)) -> RuleSummary:
    row = rule_query.get_rule_by_id(db, rule_id)
    if row is None:
        raise HTTPException(status_code=404, detail="rule not found")
    return RuleSummary.model_validate(row)