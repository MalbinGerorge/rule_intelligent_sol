"""
Read-only Cypher query logic for the graph API (UI2). Mirrors
app/services/rule_query.py's separation: this layer returns plain
dicts, never Pydantic — schema conversion happens in the endpoint layer.

NOTE: FOLLOWED_BY edges connect two BUILDING BLOCKS, tagged with
rel.rule_id identifying which rule DEFINED that sequence relationship
(see loader.py's Option C design). So "this rule's sequence
relationships" is found by filtering on that property, NOT by graph
adjacency to the rule's own node.
"""
from __future__ import annotations

from neo4j import Session as Neo4jSession


def get_rule_node(session: Neo4jSession, rule_id: int) -> dict | None:
    result = session.run(
        "MATCH (r:Rule {rule_id: $rule_id}) RETURN r", rule_id=rule_id
    ).single()
    return dict(result["r"]) if result else None


def get_rule_references(session: Neo4jSession, rule_id: int) -> list[dict]:
    """BBs this rule REFERENCES, with threshold data on the edge if present."""
    result = session.run(
        """
        MATCH (r:Rule {rule_id: $rule_id})-[rel:REFERENCES]->(bb:Rule)
        RETURN bb.identifier AS identifier, bb.name AS name, properties(rel) AS threshold
        """,
        rule_id=rule_id,
    )
    return [dict(record) for record in result]


def get_rule_conditions(session: Neo4jSession, rule_id: int) -> list[dict]:
    result = session.run(
        """
        MATCH (r:Rule {rule_id: $rule_id})-[:HAS_CONDITION]->(c:Condition)
        RETURN properties(c) AS condition
        ORDER BY c.sequence_order
        """,
        rule_id=rule_id,
    )
    return [record["condition"] for record in result]


def get_rule_logsources(session: Neo4jSession, rule_id: int) -> list[str]:
    result = session.run(
        """
        MATCH (r:Rule {rule_id: $rule_id})-[:REQUIRES_LOGSOURCE]->(ls:LogSource)
        RETURN ls.name AS name
        """,
        rule_id=rule_id,
    )
    return [record["name"] for record in result]


def get_rule_mitre(session: Neo4jSession, rule_id: int) -> list[dict]:
    result = session.run(
        """
        MATCH (r:Rule {rule_id: $rule_id})-[:DETECTS_TECHNIQUE]->(t:MitreTechnique)
        OPTIONAL MATCH (t)-[:BELONGS_TO_TACTIC]->(tac:MitreTactic)
        RETURN t.technique_id AS technique_id, t.name AS technique_name,
               tac.tactic_id AS tactic_id, tac.name AS tactic_name
        """,
        rule_id=rule_id,
    )
    return [dict(record) for record in result]


def get_rule_followed_by(session: Neo4jSession, rule_id: int) -> list[dict]:
    """Sequence relationships THIS rule defines (rel.rule_id = this rule) —
    see module docstring for why this isn't a direct-adjacency query."""
    result = session.run(
        """
        MATCH (a:Rule)-[rel:FOLLOWED_BY {rule_id: $rule_id}]->(b:Rule)
        RETURN a.identifier AS source_identifier, a.name AS source_name,
               b.identifier AS target_identifier, b.name AS target_name,
               properties(rel) AS relationship
        """,
        rule_id=rule_id,
    )
    return [dict(record) for record in result]


def get_bb_dependents(session: Neo4jSession, identifier: str, customer_id: int) -> list[dict]:
    """Which rules REFERENCE this BB — the 'blast radius' query."""
    result = session.run(
        """
        MATCH (r:Rule)-[rel:REFERENCES]->(bb:Rule {identifier: $identifier, customer_id: $customer_id})
        RETURN r.rule_id AS rule_id, r.identifier AS identifier, r.name AS name, properties(rel) AS threshold
        """,
        identifier=identifier, customer_id=customer_id,
    )
    return [dict(record) for record in result]


def get_rules_by_field(session: Neo4jSession, field: str, customer_id: int) -> list[dict]:
    result = session.run(
        """
        MATCH (r:Rule {customer_id: $customer_id})-[:HAS_CONDITION]->(c:Condition {field: $field})
        RETURN DISTINCT r.rule_id AS rule_id, r.identifier AS identifier, r.name AS name,
               c.operator AS operator, c.values AS values
        """,
        field=field, customer_id=customer_id,
    )
    return [dict(record) for record in result]


def get_rules_by_technique(session: Neo4jSession, technique_id: str, customer_id: int) -> list[dict]:
    result = session.run(
        """
        MATCH (r:Rule {customer_id: $customer_id})-[:DETECTS_TECHNIQUE]->(t:MitreTechnique {technique_id: $technique_id})
        RETURN r.rule_id AS rule_id, r.identifier AS identifier, r.name AS name
        """,
        technique_id=technique_id, customer_id=customer_id,
    )
    return [dict(record) for record in result]