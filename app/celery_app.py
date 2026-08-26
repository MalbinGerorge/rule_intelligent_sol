"""
Celery application instance -- the message queue system that lets
long-running investigations (up to 2+ minutes: multiple LLM calls,
AQL polling) survive independently of the FastAPI server's own
process lifecycle.

WHY this exists (for anyone new to Celery/Redis):
  - FastAPI's own request/response cycle is NOT the right place to run
    something that takes minutes -- the HTTP client would time out,
    and if the FastAPI server process restarts (a deploy, a crash, a
    scale-down -- all routine in production) mid-investigation, the
    work is just silently lost.
  - Celery solves this by running work in a SEPARATE process (the
    "worker"), independent of the API server. Redis is the message
    queue connecting them: FastAPI pushes "please run this task" onto
    Redis, the worker picks it up whenever it's free, runs it -- all
    independent of whether the API server that originally requested
    it is even still running.
  - TWO SEPARATE processes must be running for this to work:
      1. The FastAPI server (uvicorn) -- unchanged, still handles requests
      2. A Celery WORKER -- a new, separate process (see run instructions below)
    Both connect to the SAME Redis instance.

Run the worker (from the project root, in its own terminal, alongside
uvicorn):
    uv run celery -A app.celery_app worker --loglevel=info --pool=solo

(--pool=solo is required on Windows -- Celery's default "prefork" pool
doesn't work there. On Linux/Mac, --pool=solo can be dropped.)
"""
from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "rule_intelligent_sol",
    broker=settings.redis_url,
    backend=settings.redis_url,
    # CONFIRMED NECESSARY (found via a real test run): without this,
    # the worker process starts up with an EMPTY task list -- defining
    # @celery_app.task somewhere else isn't enough on its own; the
    # worker needs to be explicitly told which module(s) to import so
    # it actually discovers and registers the tasks defined there.
    include=["app.services.investigation_runner", "app.recommendations.sigma_batch_runner"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # A stuck/runaway task (e.g. QRadar hanging) shouldn't tie up a
    # worker forever -- set slightly above our own AQL polling ceiling
    # (2 searches x ~40s + other tool calls + LLM calls).
    task_time_limit=300,
    task_soft_time_limit=270,
)   