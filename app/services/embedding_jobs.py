"""
Job logic for embedding generation -- SAME pattern as
app/services/sigma_generation.py: potentially many representations to
embed across all customers, one Chroma upsert per batch, cannot run
inline in an HTTP request. Job status tracked in embedding_jobs,
updated incrementally so SSE shows live progress. The Celery task that
runs run_embedding_batch() is
app.workers.tasks.embeddings.run_embedding_batch_task.

Deliberately MANUAL trigger for now (not auto-chained after Sigma
generation) -- see project notes: prove this pipeline's stability
first, wire the chaining together once confidence is established.
"""

from __future__ import annotations

import json

import chromadb
import structlog
from sentence_transformers import SentenceTransformer
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.ai.retrieval.embedding_service import (
    CHROMA_COLLECTION_NAME,
    EMBEDDING_MODEL_NAME,
    build_embedding_text,
    mark_embedded,
)
from app.core.config import settings

logger = structlog.get_logger(__name__)


def create_pending_embedding_job(engine: Engine, total: int) -> int:
    with engine.begin() as db:
        row = db.execute(
            text(
                """
                INSERT INTO embedding_jobs (status, total_representations)
                VALUES ('running', :total)
                RETURNING id
                """
            ),
            {"total": total},
        )
        return row.scalar_one()


def run_embedding_batch(engine: Engine, job_id: int, representations: list[dict]) -> None:
    """CRITICAL invariant, same as run_sigma_batch: a job must NEVER
    be left stuck at status='running' forever, even on a catastrophic
    failure. One representation's failure does NOT stop the batch."""
    processed = 0
    failed = 0
    failed_details: list[dict] = []

    logger.info(
        "embedding_batch_started", job_id=job_id, total_representations=len(representations)
    )

    try:
        model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
        collection = client.get_or_create_collection(CHROMA_COLLECTION_NAME)

        for row in representations:
            try:
                doc_text = build_embedding_text(row)
                embedding = model.encode([doc_text]).tolist()[0]
                collection.upsert(
                    ids=[f"rule_{row['rule_id']}"],
                    embeddings=[embedding],
                    documents=[doc_text],
                    metadatas=[
                        {
                            "rule_id": row["rule_id"],
                            "customer_id": row["customer_id"],
                            "customer_name": row["customer_name"],
                            "title": row["title"] or "",
                            "level": row["level"] or "",
                        }
                    ],
                )
                with engine.begin() as db:
                    mark_embedded(db, row["rule_id"], row["customer_id"])
                processed += 1
            except Exception as exc:  # noqa: BLE001 -- one bad representation must not kill the whole batch
                failed += 1
                failed_details.append(
                    {
                        "rule_id": row["rule_id"],
                        "customer_id": row["customer_id"],
                        "error": str(exc),
                    }
                )
                logger.warning(
                    "embedding_representation_failed",
                    job_id=job_id,
                    rule_id=row["rule_id"],
                    customer_id=row["customer_id"],
                    error=str(exc),
                )

            with engine.begin() as db:
                db.execute(
                    text(
                        """
                        UPDATE embedding_jobs
                        SET processed_representations = :processed,
                            failed_representations = :failed,
                            failed_details = :details
                        WHERE id = :job_id
                        """
                    ),
                    {
                        "processed": processed,
                        "failed": failed,
                        "details": json.dumps(failed_details),
                        "job_id": job_id,
                    },
                )

        with engine.begin() as db:
            db.execute(
                text(
                    "UPDATE embedding_jobs SET status = 'completed', finished_at = now() WHERE id = :id"
                ),
                {"id": job_id},
            )
        logger.info("embedding_batch_completed", job_id=job_id, processed=processed, failed=failed)
    except Exception as exc:  # noqa: BLE001 -- catastrophic failure (e.g. model load, Chroma unreachable) still terminates cleanly
        logger.exception("embedding_batch_catastrophic_failure", job_id=job_id, error=str(exc))
        with engine.begin() as db:
            db.execute(
                text(
                    "UPDATE embedding_jobs SET status = 'failed', error = :error, finished_at = now() WHERE id = :id"
                ),
                {"id": job_id, "error": str(exc)},
            )
