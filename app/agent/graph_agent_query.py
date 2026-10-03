from __future__ import annotations

from neo4j import Driver
from neo4j.exceptions import ClientError
from neo4j.graph import Node, Path, Relationship

from app.agent.cypher_safety import UnsafeCypherError, validate_and_prepare

QUERY_TIMEOUT_SECONDS = 15


def _serialize_value(value):
    """Recursively converts raw Neo4j graph objects (Node/Relationship/
    Path) into plain, JSON-serializable dicts/lists. CONFIRMED
    NECESSARY from a real bug: the LLM correctly followed an early
    version of our own few-shot example that did "RETURN rel" (the raw
    relationship object) instead of "RETURN properties(rel)" — Pydantic
    can't serialize a raw neo4j.graph.Relationship, causing a 500. The
    prompt now instructs against this, but this defensive conversion
    stays regardless — the model can't be fully guaranteed to comply
    with every instruction every time, same reasoning as every other
    layer in this file."""
    if isinstance(value, (Node, Relationship)):
        return dict(value)
    if isinstance(value, Path):
        return {
            "nodes": [dict(n) for n in value.nodes],
            "relationships": [dict(r) for r in value.relationships],
        }
    if isinstance(value, list):
        return [_serialize_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}

    if hasattr(value, "to_native"):
        return value.to_native()  # e.g. neo4j.time.DateTime
    
    return value


def _run_query(tx, query: str, params: dict):
    result = tx.run(query, **params, timeout=QUERY_TIMEOUT_SECONDS)
    return [{k: _serialize_value(v) for k, v in record.items()} for record in result]


def execute_readonly_cypher(driver: Driver, query: str, params: dict | None = None) -> dict:
    """
    Validates, then executes a single LLM-generated Cypher query.

    Returns:
        {"ok": True, "rows": [...]} on success
        {"ok": False, "error": "..."} on any failure — text-level
        rejection, Neo4j's own read-transaction rejection, a syntax
        error, or a timeout. Callers should surface the error message
        back to the LLM/user rather than crash, since a malformed or
        rejected query is an expected, recoverable outcome here, not
        a bug.
    """
    params = params or {}

    try:
        safe_query = validate_and_prepare(query)
    except UnsafeCypherError as e:
        return {"ok": False, "error": f"Rejected before execution: {e}"}

    try:
        with driver.session() as session:
            rows = session.execute_read(_run_query, safe_query, params)
        return {"ok": True, "rows": rows}
    except ClientError as e:
        # Covers Neo4j's OWN rejection of a write clause inside a read
        # transaction (Neo.ClientError.Statement.AccessMode or similar)
        # — this is the case where our text-level check missed
        # something but Neo4j's server-side enforcement caught it.
        return {"ok": False, "error": f"Neo4j rejected the query: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"Query execution failed: {e}"}