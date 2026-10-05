"""Shared pytest fixtures.

Tests NEVER touch the development database. Before any `app` module is
imported, POSTGRES_DB_NAME is pointed at a separate test database on the
same Postgres server (TEST_POSTGRES_DB_NAME from the environment, else
from .env, else "rule_intelligent_sol_test"). At session
start that database is dropped, recreated and migrated with
`alembic upgrade head` -- the same migrations a real deployment runs, so
views and tables without ORM models exist too, and a broken migration
chain fails the test run.

Guard: if the database name doesn't end in "_test", the session aborts
before anything is created or dropped.

Tests that need real external services (LLMs, QRadar, Chroma, dev data)
live in evals/ instead and are run by hand, not by `pytest`.
"""
import os

from dotenv import dotenv_values

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# os.environ only sees real environment variables, not .env -- so check
# both, in the same order pydantic-settings uses (environment wins).
TEST_DB_NAME = (
    os.environ.get("TEST_POSTGRES_DB_NAME")
    or dotenv_values(os.path.join(REPO_ROOT, ".env")).get("TEST_POSTGRES_DB_NAME")
    or "rule_intelligent_sol_test"
)
# Must happen before `app` is imported: settings are read once, at import.
# Environment variables take precedence over values in .env, so this
# overrides .env's POSTGRES_DB_NAME for this pytest process only.
os.environ["POSTGRES_DB_NAME"] = TEST_DB_NAME

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.core.config import settings
from app.db.session import engine


def _assert_is_test_database() -> None:
    if not settings.postgres_db_name.endswith("_test"):
        raise pytest.UsageError(
            f"Refusing to run tests against database {settings.postgres_db_name!r}: "
            "the test database name must end in '_test'."
        )


def _recreate_test_database() -> None:
    # CREATE/DROP DATABASE can't run inside a transaction, and can't target
    # the database you're connected to -- so connect to the server's
    # built-in "postgres" maintenance database instead.
    admin_dsn = settings.pg_dsn.rsplit("/", 1)[0] + "/postgres"
    admin_engine = create_engine(admin_dsn, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    finally:
        admin_engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _test_database():
    _assert_is_test_database()
    _recreate_test_database()
    command.upgrade(Config(os.path.join(REPO_ROOT, "alembic.ini")), "head")
    yield
    engine.dispose()
