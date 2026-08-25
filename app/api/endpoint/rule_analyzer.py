"""
Async investigation API for the Rule Analyzer -- POST kicks off a
Celery task and returns immediately with an id; GET polls that id for
progress/results. A full investigation can take 30s-2+ minutes, so
this deliberately never blocks an HTTP request waiting for it to
finish -- see app/celery_app.py for the full reasoning.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.schemas.rule_analyzer import (
    InvestigationCreateResponse,
    InvestigationDetail,
    InvestigationListItem,
    InvestigationListResponse,
)
from app.dependencies.db import get_db
from app.services.investigation_runner import create_pending_investigation, run_investigation_task

router = APIRouter(prefix="/rule-analyzer", tags=["rule-analyzer"])


@router.post("/rules/{rule_id}/investigate", response_model=InvestigationCreateResponse)
def start_investigation(rule_id: int, db: Session = Depends(get_db)):
    """Creates the row immediately (status='running') and pushes the
    real work onto Redis via .delay() -- returns in milliseconds,
    the actual investigation runs later, in a separate worker process."""
    customer_id = db.execute(
        text("SELECT customer_id FROM rules WHERE id = :rule_id"), {"rule_id": rule_id}
    ).scalar_one_or_none()
    if customer_id is None:
        raise HTTPException(status_code=404, detail=f"No rule found with id {rule_id}")

    investigation_id = create_pending_investigation(db.get_bind(), customer_id, rule_id)
    run_investigation_task.delay(investigation_id, customer_id, rule_id)

    return InvestigationCreateResponse(id=investigation_id, status="running")


@router.get("/investigations/{investigation_id}", response_model=InvestigationDetail)
def get_investigation(investigation_id: int, db: Session = Depends(get_db)):
    """Poll this -- the frontend calls it every ~2s until status is
    no longer 'running'."""
    row = db.execute(
        text("SELECT * FROM investigation_reports WHERE id = :id"), {"id": investigation_id}
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No investigation found with id {investigation_id}")

    data = dict(row)
    for field in ("chain_analysis", "final_report"):
        if isinstance(data.get(field), str):
            data[field] = json.loads(data[field])

    return InvestigationDetail(**data)


@router.get("/rules/{rule_id}/investigations", response_model=InvestigationListResponse)
def list_investigations(
    rule_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """History for one rule, most recent first, paginated -- CONFIRMED
    NECESSARY: without limit/offset, older investigations beyond a
    fixed cap would be permanently unreachable through this endpoint
    once a rule accumulates enough runs. limit is capped at 100 to
    prevent a single request from pulling an unbounded number of rows."""
    total = db.execute(
        text("SELECT count(*) FROM investigation_reports WHERE rule_id = :rule_id"), {"rule_id": rule_id}
    ).scalar_one()

    rows = db.execute(
        text(
            """
            SELECT id, status, tool_calls_made, created_at
            FROM investigation_reports
            WHERE rule_id = :rule_id
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        {"rule_id": rule_id, "limit": limit, "offset": offset},
    ).mappings().all()

    return InvestigationListResponse(
        items=[InvestigationListItem(**dict(r)) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )