from collections.abc import Generator

from neo4j import Session as Neo4jSession

from app.graph.client import get_driver


def get_graph_session() -> Generator[Neo4jSession, None, None]:
    driver = get_driver()
    session = driver.session()
    try:
        yield session
    finally:
        session.close()