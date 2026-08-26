"""
Async Sigma-generation batch API. ONE endpoint handles both cases:
- POST with no rule_names (or rule_names=null) -> generates for ALL
  canonical rules for the customer.
- POST with rule_names=[...] -> generates for only those specific
  named rules.
Both require customer_name. A full customer batch can take a long
time (one LLM call per rule) -- never runs inline in the request,
same async-job pattern as the Rule Analyzer.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.schemas.recommendations import (
    SigmaGenerationJobCreateResponse,
    SigmaGenerationJobDetail,
    SigmaGenerationRequest,
)
from app.dependencies.db import get_db
from app.recommendations.sigma_batch_runner import (
    create_pending_sigma_job,
    resolve_rule_names_to_canonical_rules,
    run_sigma_batch_task,
)
from app.services.rule_query import list_canonical_rules

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.post("/customers/{customer_name}/sigma/generate", response_model=SigmaGenerationJobCreateResponse)
def start_sigma_generation(
    customer_name: str, request: SigmaGenerationRequest, db: Session = Depends(get_db)
):
    customer_id = db.execute(
        text("SELECT id FROM customers WHERE name = :n"), {"n": customer_name}
    ).scalar_one_or_none()
    if customer_id is None:
        raise HTTPException(status_code=404, detail=f"No customer named '{customer_name}'")

    if request.rule_names:
        found, not_found = resolve_rule_names_to_canonical_rules(db, customer_id, request.rule_names)
        if not_found:
            raise HTTPException(status_code=400, detail=f"Rule name(s) not found: {not_found}")
        rules_to_process = found
    else:
        rules_to_process = list_canonical_rules(db, customer_id)

    job_id = create_pending_sigma_job(db.get_bind(), customer_id, request.rule_names, len(rules_to_process))

    rules_payload = [{"id": r["id"], "name": r["name"]} for r in rules_to_process]
    run_sigma_batch_task.delay(job_id, customer_id, rules_payload)

    return SigmaGenerationJobCreateResponse(id=job_id, status="running", total_rules=len(rules_to_process))


@router.get("/sigma-jobs/{job_id}", response_model=SigmaGenerationJobDetail)
def get_sigma_job(job_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("SELECT * FROM sigma_generation_jobs WHERE id = :id"), {"id": job_id}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No job found with id {job_id}")

    data = dict(row)
    for field in ("requested_rule_names", "failed_rule_details"):
        if isinstance(data.get(field), str):
            data[field] = json.loads(data[field])
    return SigmaGenerationJobDetail(**data)