"""
Background execution wrapper for the Rule Analyzer's investigation
graph, run via Celery so long-running work (30s-2+ minutes: multiple
LLM calls, AQL polling) survives independently of the FastAPI server's
own process lifecycle -- see app/celery_app.py's docstring for the
full explanation of why this is needed.

create_pending_investigation() and run_and_store_investigation() are
plain, framework-agnostic functions (CONFIRMED via test: the critical
"never stuck at running, even on failure" invariant holds). The Celery
TASK (run_investigation_task, at the bottom) is a thin wrapper around
these -- no new logic there, just the queueing mechanism.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.rule_analyzer.investigation_graph import run_investigation
from app.rule_analyzer.llm_provider import LLMProvider
from app.services.qradar_client_factory import build_qradar_client_for_customer


def create_pending_investigation(engine: Engine, customer_id: int, rule_id: int) -> int:
    """Creates the row immediately, status='running', everything else
    NULL -- so the caller gets an id to poll right away, before any
    actual work has happened."""
    with engine.begin() as db:
        row = db.execute(
            text(
                """
                INSERT INTO investigation_reports (customer_id, rule_id, status)
                VALUES (:customer_id, :rule_id, 'running')
                RETURNING id
                """
            ),
            {"customer_id": customer_id, "rule_id": rule_id},
        )
        return row.scalar_one()


def run_and_store_investigation(engine: Engine, investigation_id: int, customer_id: int, rule_id: int) -> None:
    """The actual background work. Called via a Celery task (see
    run_investigation_task below) -- takes the ENGINE (not a
    request-scoped db session), since this runs in a completely
    separate WORKER process, independent of the original HTTP
    request; it opens its OWN fresh connection(s).

    CRITICAL invariant, CONFIRMED via test: a row must NEVER be left
    stuck at status='running' forever, even if the investigation
    raises. The try/except structure guarantees a terminal status
    ('completed' or 'failed') is always written."""
    try:
        with engine.connect() as db:
            qradar_client = build_qradar_client_for_customer(db, customer_id)
            provider = LLMProvider()
            result = run_investigation(db, provider, qradar_client, customer_id, rule_id)

        chain_analysis = result.get("chain_analysis")
        final_report_structured = result.get("final_report_structured")

        with engine.begin() as db:
            db.execute(
                text(
                    """
                    UPDATE investigation_reports
                    SET status = 'completed',
                        chain_analysis = :chain_analysis,
                        final_report = :final_report,
                        rendered_report = :rendered_report,
                        trace = :trace,
                        tool_calls_made = :tool_calls_made
                    WHERE id = :id
                    """
                ),
                {
                    "id": investigation_id,
                    "chain_analysis": chain_analysis.model_dump_json() if chain_analysis else None,
                    "final_report": final_report_structured.model_dump_json() if final_report_structured else None,
                    "rendered_report": result.get("final_report"),
                    "trace": result.get("trace"),
                    "tool_calls_made": result.get("tool_calls_made"),
                },
            )
    except Exception as exc:  # noqa: BLE001 -- deliberately broad: ANY failure must still mark the row terminal
        with engine.begin() as db:
            db.execute(
                text("UPDATE investigation_reports SET status = 'failed', error = :error WHERE id = :id"),
                {"id": investigation_id, "error": str(exc)},
            )


from app.celery_app import celery_app  # noqa: E402 -- placed here to avoid a circular import at module load time
from app.db.session import engine as _shared_engine  # noqa: E402


@celery_app.task(name="run_investigation_task")
def run_investigation_task(investigation_id: int, customer_id: int, rule_id: int) -> None:
    """The Celery TASK -- what actually gets queued onto Redis and
    picked up by an independent WORKER process. A thin wrapper around
    the already-tested run_and_store_investigation() -- no new logic
    here, so the tested status-transition guarantees (never stuck at
    'running', even on failure) carry over unchanged."""
    run_and_store_investigation(_shared_engine, investigation_id, customer_id, rule_id)