"""
Async batch execution for Sigma generation across many rules --
same reasoning as investigation_runner.py: an LLM call per rule,
potentially hundreds of rules, cannot run inside a single HTTP
request. Job status tracked in sigma_generation_jobs, updated
incrementally so polling shows live progress.
"""
from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.recommendations.sigma_generator import SigmaGenerator
from app.rule_analyzer.llm_provider import LLMProvider
from app.services.rule_query import list_canonical_rules


def resolve_rule_names_to_canonical_rules(
    db: Session, customer_id: int, rule_names: list[str]
) -> tuple[list[dict], list[str]]:
    """Returns (found_rules, not_found_names). Uses list_canonical_rules
    internally, so name lookups automatically respect the override-pair
    deduplication already built -- a name resolves to its real,
    currently-active row, never a stale SYSTEM stub."""
    canonical = list_canonical_rules(db, customer_id)
    name_to_rule = {r["name"]: r for r in canonical}
    found = [name_to_rule[name] for name in rule_names if name in name_to_rule]
    not_found = [name for name in rule_names if name not in name_to_rule]
    return found, not_found


def create_pending_sigma_job(
    engine: Engine, customer_id: int, requested_rule_names: list[str] | None, total_rules: int
) -> int:
    with engine.begin() as db:
        row = db.execute(
            text(
                """
                INSERT INTO sigma_generation_jobs (customer_id, status, requested_rule_names, total_rules)
                VALUES (:customer_id, 'running', :names, :total)
                RETURNING id
                """
            ),
            {
                "customer_id": customer_id,
                "names": json.dumps(requested_rule_names) if requested_rule_names else None,
                "total": total_rules,
            },
        )
        return row.scalar_one()


def run_sigma_batch(engine: Engine, job_id: int, customer_id: int, rules: list[dict]) -> None:
    """rules: list of {"id": rule_id, "name": rule_name}. CRITICAL
    invariant, same as investigation_runner.py: a job must NEVER be
    left stuck at status='running' forever, even if something
    catastrophic happens mid-run. A single rule's failure does NOT
    stop the batch -- it's recorded and processing continues."""
    provider = LLMProvider()
    generator = SigmaGenerator(provider)
    processed = 0
    failed = 0
    failed_details: list[dict] = []

    try:
        for rule in rules:
            try:
                with engine.begin() as db:
                    generator.generate_and_save(db, customer_id, rule["id"])
                processed += 1
            except Exception as exc:  # noqa: BLE001 -- one bad rule must not kill the whole batch
                failed += 1
                failed_details.append({"rule_id": rule["id"], "rule_name": rule["name"], "error": str(exc)})

            with engine.begin() as db:
                db.execute(
                    text(
                        """
                        UPDATE sigma_generation_jobs
                        SET processed_rules = :processed, failed_rules = :failed, failed_rule_details = :details
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
                text("UPDATE sigma_generation_jobs SET status = 'completed', finished_at = now() WHERE id = :id"),
                {"id": job_id},
            )
    except Exception as exc:  # noqa: BLE001 -- catastrophic failure (e.g. DB connection lost) still must terminate cleanly
        with engine.begin() as db:
            db.execute(
                text(
                    "UPDATE sigma_generation_jobs SET status = 'failed', error = :error, finished_at = now() WHERE id = :id"
                ),
                {"id": job_id, "error": str(exc)},
            )


from app.celery_app import celery_app  # noqa: E402 -- avoids circular import at module load time
from app.db.session import engine as _shared_engine  # noqa: E402


@celery_app.task(name="run_sigma_batch_task")
def run_sigma_batch_task(job_id: int, customer_id: int, rules: list[dict]) -> None:
    """The Celery TASK -- thin wrapper, no new logic, same pattern as
    run_investigation_task."""
    run_sigma_batch(_shared_engine, job_id, customer_id, rules)