"""
Recommendation system endpoints: async Sigma generation (with SSE
progress), exact-category gap analysis (MITRE technique + log source
type), and intent-based semantic search over embedded Sigma rules.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps.db import get_db
from app.api.schemas.embeddings import (
    EmbeddingJobCreateResponse,
    EmbeddingJobDetail,
    SimilaritySearchRequest,
)
from app.api.schemas.recommendations import (
    LogSourceGap,
    MitreGap,
    SigmaGenerationJobCreateResponse,
    SigmaGenerationJobDetail,
    SigmaGenerationRequest,
    SimilaritySearchResult,
)
from app.core.exceptions import NotFoundError
from app.db.session import engine as sync_engine
from app.integrations.neo4j.client import get_driver
from app.recommendations.embedding_batch_runner import (
    create_pending_embedding_job,
    run_embedding_batch_task,
)
from app.recommendations.embedding_service import get_stale_representations
from app.recommendations.log_source_gap_analyzer import LogSourceGapAnalyzer
from app.recommendations.mitre_gap_analyzer import MitreGapAnalyzer
from app.recommendations.sigma_batch_runner import (
    create_pending_sigma_job,
    get_rule_ids_with_existing_sigma,
    resolve_rule_names_to_canonical_rules,
    run_sigma_batch_task,
)
from app.recommendations.similarity_search import SimilaritySearchService
from app.services.rule_query import list_canonical_rules

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

SSE_POLL_INTERVAL_SECONDS = 1.5


def _row_to_json_dict(row) -> dict:
    data = dict(row)
    for field in ("requested_rule_names", "failed_rule_details", "failed_details"):
        if isinstance(data.get(field), str):
            data[field] = json.loads(data[field])
    for field in ("created_at", "finished_at"):
        if data.get(field) is not None:
            data[field] = data[field].isoformat()
    return data


def _resolve_customer_id(db: Session, customer_name: str) -> int:
    customer_id = db.execute(
        text("SELECT id FROM customers WHERE name = :n"), {"n": customer_name}
    ).scalar_one_or_none()
    if customer_id is None:
        raise NotFoundError(f"No customer named '{customer_name}'")
    return customer_id


# ============================================================
# Sigma generation (async, Celery + SSE)
# ============================================================


@router.post(
    "/customers/{customer_name}/sigma/generate", response_model=SigmaGenerationJobCreateResponse
)
def start_sigma_generation(
    customer_name: str, request: SigmaGenerationRequest, db: Session = Depends(get_db)
):
    customer_id = _resolve_customer_id(db, customer_name)

    if request.rule_names:
        found, not_found = resolve_rule_names_to_canonical_rules(
            db, customer_id, request.rule_names
        )
        if not_found:
            raise NotFoundError(f"Rule name(s) not found: {not_found}")
        rules_to_process = found
    else:
        all_rules = list_canonical_rules(db, customer_id)
        up_to_date = get_rule_ids_with_existing_sigma(db, customer_id)
        rules_to_process = [r for r in all_rules if r["id"] not in up_to_date]

    job_id = create_pending_sigma_job(
        db.get_bind(), customer_id, request.rule_names, len(rules_to_process)
    )
    rules_payload = [{"id": r["id"], "name": r["name"]} for r in rules_to_process]
    run_sigma_batch_task.delay(job_id, customer_id, customer_name, rules_payload)

    return SigmaGenerationJobCreateResponse(
        id=job_id, status="running", total_rules=len(rules_to_process)
    )


@router.get("/sigma-jobs/{job_id}", response_model=SigmaGenerationJobDetail)
def get_sigma_job(job_id: int, db: Session = Depends(get_db)):
    row = (
        db.execute(text("SELECT * FROM sigma_generation_jobs WHERE id = :id"), {"id": job_id})
        .mappings()
        .first()
    )
    if row is None:
        raise NotFoundError(f"No job found with id {job_id}")
    return SigmaGenerationJobDetail(**_row_to_json_dict(row))


@router.get("/sigma-jobs/{job_id}/stream")
async def stream_sigma_job(job_id: int):
    async def event_generator():
        last_processed = -1
        last_status = None
        while True:
            with sync_engine.connect() as db:
                row = (
                    db.execute(
                        text("SELECT * FROM sigma_generation_jobs WHERE id = :id"), {"id": job_id}
                    )
                    .mappings()
                    .first()
                )
            if row is None:
                yield f"event: error\ndata: {json.dumps({'error': 'job not found'})}\n\n"
                return
            data = _row_to_json_dict(row)
            if data["processed_rules"] != last_processed or data["status"] != last_status:
                yield f"data: {json.dumps(data)}\n\n"
                last_processed = data["processed_rules"]
                last_status = data["status"]
            if data["status"] != "running":
                return
            await asyncio.sleep(SSE_POLL_INTERVAL_SECONDS)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ============================================================
# Exact-category gap analysis (MITRE technique + log source type)
# ============================================================


@router.get("/customers/{customer_name}/mitre-gaps", response_model=list[MitreGap])
def get_mitre_gaps(customer_name: str, db: Session = Depends(get_db)):
    customer_id = _resolve_customer_id(db, customer_name)
    analyzer = MitreGapAnalyzer(db, get_driver())
    return analyzer.analyze(customer_id)


@router.get("/customers/{customer_name}/log-source-gaps", response_model=list[LogSourceGap])
def get_log_source_gaps(customer_name: str, db: Session = Depends(get_db)):
    customer_id = _resolve_customer_id(db, customer_name)
    analyzer = LogSourceGapAnalyzer(db, get_driver())
    return analyzer.analyze(customer_id)


# ============================================================
# Semantic embedding generation (async, Celery + SSE) + search (sync)
# ============================================================


@router.post("/embeddings/generate", response_model=EmbeddingJobCreateResponse)
def start_embedding_generation(db: Session = Depends(get_db)):
    stale = get_stale_representations(db)
    job_id = create_pending_embedding_job(db.get_bind(), len(stale))
    run_embedding_batch_task.delay(job_id, stale)
    return EmbeddingJobCreateResponse(id=job_id, status="running", total_representations=len(stale))


@router.get("/embeddings-jobs/{job_id}", response_model=EmbeddingJobDetail)
def get_embedding_job(job_id: int, db: Session = Depends(get_db)):
    row = (
        db.execute(text("SELECT * FROM embedding_jobs WHERE id = :id"), {"id": job_id})
        .mappings()
        .first()
    )
    if row is None:
        raise NotFoundError(f"No embedding job found with id {job_id}")
    return EmbeddingJobDetail(**_row_to_json_dict(row))


@router.get("/embeddings-jobs/{job_id}/stream")
async def stream_embedding_job(job_id: int):
    async def event_generator():
        last_processed = -1
        last_status = None
        while True:
            with sync_engine.connect() as db:
                row = (
                    db.execute(text("SELECT * FROM embedding_jobs WHERE id = :id"), {"id": job_id})
                    .mappings()
                    .first()
                )
            if row is None:
                yield f"event: error\ndata: {json.dumps({'error': 'job not found'})}\n\n"
                return
            data = _row_to_json_dict(row)
            if data["processed_representations"] != last_processed or data["status"] != last_status:
                yield f"data: {json.dumps(data)}\n\n"
                last_processed = data["processed_representations"]
                last_status = data["status"]
            if data["status"] != "running":
                return
            await asyncio.sleep(SSE_POLL_INTERVAL_SECONDS)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/customers/{customer_name}/similarity-search", response_model=SimilaritySearchResult)
def similarity_search(
    customer_name: str, request: SimilaritySearchRequest, db: Session = Depends(get_db)
):
    """Synchronous -- fast enough (one query embed + one Chroma lookup)
    to run inline, unlike embedding GENERATION which needs Celery."""
    customer_id = _resolve_customer_id(db, customer_name)
    service = SimilaritySearchService(db)
    return service.search(customer_id, request.query)
