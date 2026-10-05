"""Celery task for Sigma generation batches. Queueing only: the job logic
lives in app/services/sigma_generation.py."""

from __future__ import annotations

from app.db.session import engine
from app.services.sigma_generation import run_sigma_batch
from app.workers.celery_app import celery_app


@celery_app.task(name="run_sigma_batch_task")
def run_sigma_batch_task(
    job_id: int, customer_id: int, customer_name: str, rules: list[dict]
) -> None:
    run_sigma_batch(engine, job_id, customer_id, customer_name, rules)
