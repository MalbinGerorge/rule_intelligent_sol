"""
Safety layer for LLM-generated Cypher, before it ever touches Neo4j.

TWO layers of defense, deliberately not relying on either alone:
  1. Text-level pre-check (this module): fast, cheap, catches obvious
     write attempts immediately, before any Neo4j round-trip. NOT
     bulletproof on its own — a determined adversarial query could in
     principle dodge a pure regex check (comments, string escaping,
     odd whitespace).
  2. Neo4j's own read-only transaction mode (see execute_readonly_cypher
     in app/agent/graph_agent_query.py): the AUTHORITATIVE enforcement.
     Running a query via session.execute_read() puts the transaction in
     READ access mode server-side — Neo4j itself refuses any write
     clause inside it, regardless of what the query text says. This is
     the real guarantee; the text-level check here is just an early,
     fast rejection for the common case.

customer_id scoping: this module can only do a HEURISTIC text check
(does the query reference $customer_id or customer_id: anywhere at
all) — it cannot verify every MATCH clause is correctly scoped. This
is a genuine, honest limitation of text-level validation, not
something Neo4j Community edition enforces at the row-security level
the way some other databases do. Treat this check as "catches
completely unscoped queries," not "guarantees perfect isolation."
"""
from __future__ import annotations

import re

# Case-insensitive, word-boundary match against Cypher's write clauses
# and known-dangerous procedure calls. Checked against the raw query
# text as the fast first-pass rejection.
_WRITE_KEYWORDS = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD\s+CSV)\b",
    re.IGNORECASE,
)

# Specific dangerous procedure call prefixes — apoc write procedures,
# admin/dbms procedures — even though these appear as CALL, which
# itself isn't in the write-keyword list above (CALL is also used for
# legitimate read procedures like db.labels()).
_DANGEROUS_CALL_PREFIXES = re.compile(
    r"\bCALL\s+(apoc\.(create|merge|refactor|periodic)|dbms\.|db\.(create|drop|index\.create|constraint))",
    re.IGNORECASE,
)

_LIMIT_PATTERN = re.compile(r"\bLIMIT\s+\d+\b", re.IGNORECASE)

DEFAULT_ROW_LIMIT = 200


class UnsafeCypherError(Exception):
    """Raised when a generated Cypher query fails the safety pre-check."""


def check_read_only(query: str) -> None:
    """Raises UnsafeCypherError if the query text contains any write
    clause or dangerous procedure call. Fast, text-level pre-check —
    NOT the authoritative guarantee, see module docstring."""
    write_match = _WRITE_KEYWORDS.search(query)
    if write_match:
        raise UnsafeCypherError(
            f"Query contains a write clause ('{write_match.group(1)}'). "
            "Only read-only (MATCH/RETURN) queries are permitted."
        )

    call_match = _DANGEROUS_CALL_PREFIXES.search(query)
    if call_match:
        raise UnsafeCypherError(
            f"Query calls a disallowed procedure ('{call_match.group(0)}')."
        )


def check_customer_scoped(query: str) -> None:
    """Heuristic check: does the query reference customer_id anywhere
    at all? Catches completely unscoped queries. Does NOT guarantee
    every clause is correctly scoped — see module docstring."""
    if "customer_id" not in query:
        raise UnsafeCypherError(
            "Query does not reference customer_id anywhere — refusing "
            "to run a completely unscoped query against a multi-tenant graph."
        )


def ensure_limit(query: str, default_limit: int = DEFAULT_ROW_LIMIT) -> str:
    """Appends a LIMIT clause if the query doesn't already have one,
    preventing an unbounded result set. If a LIMIT is already present,
    the query is returned unchanged (we don't second-guess an
    explicit, reasonable limit the LLM already chose)."""
    if _LIMIT_PATTERN.search(query):
        return query
    return f"{query.rstrip().rstrip(';')}\nLIMIT {default_limit}"


def validate_and_prepare(query: str, default_limit: int = DEFAULT_ROW_LIMIT) -> str:
    """Runs all text-level checks, then returns the query with a LIMIT
    guaranteed. Raises UnsafeCypherError on any failure. This is the
    single entry point callers should use — see also
    execute_readonly_cypher for the second, authoritative layer."""
    check_read_only(query)
    check_customer_scoped(query)
    return ensure_limit(query, default_limit)