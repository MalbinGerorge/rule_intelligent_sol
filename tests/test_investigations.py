"""The investigation job's core guarantee: a row never stays at
status='running', whatever happens during the investigation. QRadar, the
LLM provider and the LangGraph run are replaced with stand-ins; the
database is the real (test) Postgres."""

import uuid

import pytest
from sqlalchemy import text

import app.services.investigations as investigations
from app.db.session import engine
from app.workers.tasks import investigation as investigation_task


@pytest.fixture
def rule():
    """A customer and one rule to investigate, removed afterwards."""
    with engine.begin() as db:
        customer_id = db.execute(
            # verify_ssl/active have only ORM-side defaults, so raw SQL must set them
            text(
                "INSERT INTO customers (name, qradar_host, verify_ssl, active)"
                " VALUES (:n, 'qradar.test', true, true) RETURNING id"
            ),
            {"n": f"test-{uuid.uuid4().hex[:8]}"},
        ).scalar_one()
        rule_id = db.execute(
            text(
                "INSERT INTO rules (customer_id, qradar_rule_id) VALUES (:c, 100001) RETURNING id"
            ),
            {"c": customer_id},
        ).scalar_one()
    yield customer_id, rule_id
    with engine.begin() as db:
        db.execute(
            text("DELETE FROM investigation_reports WHERE customer_id = :c"), {"c": customer_id}
        )
        db.execute(text("DELETE FROM rules WHERE customer_id = :c"), {"c": customer_id})
        db.execute(text("DELETE FROM customers WHERE id = :c"), {"c": customer_id})


@pytest.fixture
def no_external_calls(monkeypatch):
    monkeypatch.setattr(
        investigations, "build_qradar_client_for_customer", lambda db, cid: object()
    )
    monkeypatch.setattr(investigations, "LLMProvider", lambda: object())


def _row(investigation_id: int) -> dict:
    with engine.connect() as db:
        return dict(
            db.execute(
                text("SELECT * FROM investigation_reports WHERE id = :id"), {"id": investigation_id}
            )
            .mappings()
            .one()
        )


def test_new_investigation_starts_running(rule):
    customer_id, rule_id = rule
    investigation_id = investigations.create_pending_investigation(engine, customer_id, rule_id)

    assert _row(investigation_id)["status"] == "running"


def test_investigation_that_raises_is_marked_failed(rule, no_external_calls, monkeypatch):
    customer_id, rule_id = rule

    def explode(*args, **kwargs):
        raise RuntimeError("AQL search timed out")

    monkeypatch.setattr(investigations, "run_investigation", explode)
    investigation_id = investigations.create_pending_investigation(engine, customer_id, rule_id)

    investigations.run_and_store_investigation(engine, investigation_id, customer_id, rule_id)

    row = _row(investigation_id)
    assert row["status"] == "failed"
    assert row["error"] == "AQL search timed out"


def test_successful_investigation_stores_the_report(rule, no_external_calls, monkeypatch):
    customer_id, rule_id = rule
    monkeypatch.setattr(
        investigations,
        "run_investigation",
        lambda *args: {
            "chain_analysis": None,
            "final_report_structured": None,
            "final_report": "## Report",
            "trace": "analyze_chain -> synthesize_report",
            "tool_calls_made": 2,
        },
    )
    investigation_id = investigations.create_pending_investigation(engine, customer_id, rule_id)

    investigations.run_and_store_investigation(engine, investigation_id, customer_id, rule_id)

    row = _row(investigation_id)
    assert row["status"] == "completed"
    assert row["rendered_report"] == "## Report"
    assert row["tool_calls_made"] == 2
    assert row["error"] is None


def test_celery_task_only_delegates_to_the_service(monkeypatch):
    calls = []
    monkeypatch.setattr(
        investigation_task, "run_and_store_investigation", lambda *args: calls.append(args)
    )

    investigation_task.run_investigation_task(7, 3, 42)  # runs inline; no broker involved

    assert calls == [(engine, 7, 3, 42)]
