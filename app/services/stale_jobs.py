"""Mark background jobs that have been 'running' far too long as failed.

A job row is created with status 'running' before its Celery task starts,
and the task's try/except guarantees a terminal status for any error the
task itself raises. It can't help when the worker process dies (crash,
kill, restart) or the task never reaches a worker: the row then stays
'running' forever and the UI shows a job that will never finish.

This finds those rows and marks them failed with an explanation. It is
deliberately conservative -- a job counts as stale only after
`older_than` (default 7 days; real jobs here have taken up to ~16 hours)
because without a heartbeat it can't tell a slow job from a dead one.
Phase 3 of the database redesign adds heartbeats to a single jobs table
and schedules this check (Celery beat) with a much shorter threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.engine import Engine

DEFAULT_OLDER_THAN = timedelta(days=7)

# table -> whether it has a finished_at column
JOB_TABLES = {
    "embedding_jobs": True,
    "sigma_generation_jobs": True,
    "investigation_reports": False,
}


@dataclass(frozen=True)
class StaleJob:
    table: str
    id: int
    created_at: str


def find_stale_jobs(engine: Engine, older_than: timedelta = DEFAULT_OLDER_THAN) -> list[StaleJob]:
    stale: list[StaleJob] = []
    with engine.connect() as db:
        for table in JOB_TABLES:
            rows = db.execute(
                text(
                    f"SELECT id, created_at FROM {table} "
                    "WHERE status = 'running' AND created_at < now() - :older_than ORDER BY id"
                ),
                {"older_than": older_than},
            )
            stale += [StaleJob(table, r.id, r.created_at.isoformat()) for r in rows]
    return stale


def fail_stale_jobs(engine: Engine, older_than: timedelta = DEFAULT_OLDER_THAN) -> list[StaleJob]:
    """Marks every stale job failed in one transaction; returns them."""
    stale = find_stale_jobs(engine, older_than)
    error = (
        f"Marked failed automatically: still 'running' after more than {older_than}. "
        "The worker most likely stopped (crash or restart) or never received the task. "
        "Start the job again."
    )
    with engine.begin() as db:
        for job in stale:
            finished = ", finished_at = now()" if JOB_TABLES[job.table] else ""
            db.execute(
                text(
                    f"UPDATE {job.table} SET status = 'failed', error = :error{finished} "
                    "WHERE id = :id AND status = 'running'"
                ),
                {"id": job.id, "error": error},
            )
    return stale
