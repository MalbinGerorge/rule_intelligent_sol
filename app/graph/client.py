"""
Neo4j connection layer. Mirrors app/db/session.py's pattern for
Postgres — one driver instance, created from settings, reused
everywhere rather than each caller opening its own connection.
"""
from __future__ import annotations

from neo4j import Driver, GraphDatabase

from app.core.config import settings

_driver: Driver | None = None


def get_driver() -> Driver:
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password),
        )
    return _driver


def close_driver() -> None:
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None