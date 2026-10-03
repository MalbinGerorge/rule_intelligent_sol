"""
Async batch execution for Sigma generation across many rules --
same reasoning as investigation_runner.py: an LLM call per rule,
potentially hundreds of rules, cannot run inside a single HTTP
request. Job status tracked in sigma_generation_jobs, updated
incrementally so polling/SSE shows live progress.

customer_name is threaded through (not just customer_id) so LangSmith
tracing can be split per customer AND per operation --
"{customer_name}-sigma-generation" -- matching the naming convention
used elsewhere. Set as an env var at the START of run_sigma_batch,
before any LLM calls happen.
"""
from __future__ import annotations

import json
import os

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.recommendations.sigma_generator import SigmaGenerator
from app.rule_analyzer.llm_provider import LLMProvider
from app.services.rule_query import list_canonical_rules


def resolve_rule_names_to_canonical_rules(
    db: Session, customer_id: int, rule_names: list[str]
) -> tuple[list[dict], list[str]]:
    canonical = list_canonical_rules(db, customer_id)
    name_to_rule = {r["name"]: r for r in canonical}
    found = [name_to_rule[name] for name in rule_names if name in name_to_rule]
    not_found = [name for name in rule_names if name not in name_to_rule]
    return found, not_found


def get_rule_ids_with_existing_sigma(db: Session, customer_id: int) -> set[int]:
    """Rule ids with an EXISTING, STILL-CURRENT Sigma representation --
    NOT just "any row exists," but "the rule hasn't been modified in
    QRadar since its Sigma was last generated." Same staleness-
    detection PRINCIPLE as rules.needs_reparse (rule_ingest.py),
    applied as a cross-table comparison here since
    rule_yaml_representations isn't an upsert-in-place table the way
    rules is. A rule genuinely edited in QRadar after its Sigma was
    generated correctly falls OUT of this set, so it gets regenerated
    instead of being silently skipped forever with stale output."""
    rows = db.execute(
        text(
            """
            SELECT ryr.rule_id
            FROM rule_yaml_representations ryr
            JOIN rule_summary rs ON rs.id = ryr.rule_id
            WHERE ryr.customer_id = :customer_id
            GROUP BY ryr.rule_id, rs.updated_at
            HAVING rs.updated_at <= MAX(ryr.generated_at)
            """
        ),
        {"customer_id": customer_id},
    ).fetchall()
    return {r[0] for r in rows}


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


def run_sigma_batch(
    engine: Engine, job_id: int, customer_id: int, customer_name: str, rules: list[dict]
) -> None:
    """rules: list of {"id": rule_id, "name": rule_name}. CRITICAL
    invariant, same as investigation_runner.py: a job must NEVER be
    left stuck at status='running' forever, even if something
    catastrophic happens mid-run. A single rule's failure does NOT
    stop the batch -- it's recorded and processing continues."""
    os.environ["LANGCHAIN_PROJECT"] = f"{customer_name}-sigma-generation"

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
            except Exception as exc:
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
    except Exception as exc:
        with engine.begin() as db:
            db.execute(
                text(
                    "UPDATE sigma_generation_jobs SET status = 'failed', error = :error, finished_at = now() WHERE id = :id"
                ),
                {"id": job_id, "error": str(exc)},
            )


from app.celery_app import celery_app  # noqa: E402
from app.db.session import engine as _shared_engine  # noqa: E402


@celery_app.task(name="run_sigma_batch_task")
def run_sigma_batch_task(job_id: int, customer_id: int, customer_name: str, rules: list[dict]) -> None:
    run_sigma_batch(_shared_engine, job_id, customer_id, customer_name, rules)