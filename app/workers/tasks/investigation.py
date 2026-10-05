"""Celery task for Rule Analyzer investigations. Queueing only: the job
logic, including the "never stuck at running" guarantee, lives in
app/services/investigations.py."""

from __future__ import annotations

from app.db.session import engine
from app.services.investigations import run_and_store_investigation
from app.workers.celery_app import celery_app


@celery_app.task(name="run_investigation_task")
def run_investigation_task(investigation_id: int, customer_id: int, rule_id: int) -> None:
    run_and_store_investigation(engine, investigation_id, customer_id, rule_id)
