"""Celery task for embedding batches. Queueing only: the job logic lives
in app/services/embedding_jobs.py."""

from __future__ import annotations

from app.db.session import engine
from app.services.embedding_jobs import run_embedding_batch
from app.workers.celery_app import celery_app


@celery_app.task(name="run_embedding_batch_task")
def run_embedding_batch_task(job_id: int, representations: list[dict]) -> None:
    run_embedding_batch(engine, job_id, representations)
