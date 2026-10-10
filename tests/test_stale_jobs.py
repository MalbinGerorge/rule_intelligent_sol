"""Stale-job cleanup: only jobs 'running' longer than the threshold are
failed; recent running jobs and finished jobs are never touched."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.db.session import engine
from app.services.stale_jobs import fail_stale_jobs, find_stale_jobs


@pytest.fixture
def jobs():
    with engine.begin() as db:
        customer_id = db.execute(
            text(
                "INSERT INTO customers (name, qradar_host, verify_ssl, active)"
                " VALUES (:n, 'qradar.test', true, true) RETURNING id"
            ),
            {"n": f"test-{uuid.uuid4().hex[:8]}"},
        ).scalar_one()
        rule_id = db.execute(
            text("INSERT INTO rules (customer_id, qradar_rule_id) VALUES (:c, 1) RETURNING id"),
            {"c": customer_id},
        ).scalar_one()

        def embedding(status, age):
            return db.execute(
                text(
                    "INSERT INTO embedding_jobs (status, created_at)"
                    " VALUES (:s, now() - CAST(:age AS interval)) RETURNING id"
                ),
                {"s": status, "age": age},
            ).scalar_one()

        ids = {
            "embedding_old_running": embedding("running", "10 days"),
            "embedding_recent_running": embedding("running", "1 hour"),
            "embedding_old_completed": embedding("completed", "30 days"),
            "sigma_old_running": db.execute(
                text(
                    "INSERT INTO sigma_generation_jobs (customer_id, status, created_at)"
                    " VALUES (:c, 'running', now() - interval '8 days') RETURNING id"
                ),
                {"c": customer_id},
            ).scalar_one(),
            "investigation_old_running": db.execute(
                text(
                    "INSERT INTO investigation_reports (customer_id, rule_id, status, created_at)"
                    " VALUES (:c, :r, 'running', now() - interval '9 days') RETURNING id"
                ),
                {"c": customer_id, "r": rule_id},
            ).scalar_one(),
        }
    yield ids
    with engine.begin() as db:
        db.execute(
            text("DELETE FROM embedding_jobs WHERE id = ANY(:ids)"), {"ids": list(ids.values())}
        )
        db.execute(
            text("DELETE FROM sigma_generation_jobs WHERE customer_id = :c"), {"c": customer_id}
        )
        db.execute(
            text("DELETE FROM investigation_reports WHERE customer_id = :c"), {"c": customer_id}
        )
        db.execute(text("DELETE FROM rules WHERE customer_id = :c"), {"c": customer_id})
        db.execute(text("DELETE FROM customers WHERE id = :c"), {"c": customer_id})


def _row(table: str, job_id: int):
    with engine.connect() as db:
        return (
            db.execute(text(f"SELECT * FROM {table} WHERE id = :id"), {"id": job_id})
            .mappings()
            .one()
        )


def _found(jobs: dict, stale) -> set[str]:
    by_key = {
        (t, i): k
        for k, i in jobs.items()
        for t in ("embedding_jobs", "sigma_generation_jobs", "investigation_reports")
        if k.startswith(t.split("_")[0])
    }
    return {by_key[(s.table, s.id)] for s in stale if (s.table, s.id) in by_key}


def test_dry_run_finds_only_old_running_jobs_and_changes_nothing(jobs):
    stale = find_stale_jobs(engine)

    assert _found(jobs, stale) == {
        "embedding_old_running",
        "sigma_old_running",
        "investigation_old_running",
    }
    assert _row("embedding_jobs", jobs["embedding_old_running"])["status"] == "running"


def test_apply_fails_only_old_running_jobs(jobs):
    fail_stale_jobs(engine)

    old = _row("embedding_jobs", jobs["embedding_old_running"])
    assert old["status"] == "failed"
    assert old["finished_at"] is not None
    assert "Marked failed automatically" in old["error"]
    assert _row("sigma_generation_jobs", jobs["sigma_old_running"])["status"] == "failed"
    assert _row("investigation_reports", jobs["investigation_old_running"])["status"] == "failed"

    assert _row("embedding_jobs", jobs["embedding_recent_running"])["status"] == "running"
    completed = _row("embedding_jobs", jobs["embedding_old_completed"])
    assert completed["status"] == "completed" and completed["error"] is None


def test_threshold_is_respected(jobs):
    assert _found(jobs, find_stale_jobs(engine, older_than=timedelta(days=30))) == set()
    assert "embedding_recent_running" in _found(
        jobs, find_stale_jobs(engine, older_than=timedelta(minutes=1))
    )
