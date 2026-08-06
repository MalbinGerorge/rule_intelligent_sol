"""Shared pytest fixtures.

TODO: point this at a disposable test database (or use a transaction
that's rolled back per test) once ingestion services exist to test.
Left minimal for now since there's no business logic yet to exercise.
"""
import pytest

from app.db.base import Base
from app.db.session import engine


@pytest.fixture(scope="session", autouse=True)
def _db_schema():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)