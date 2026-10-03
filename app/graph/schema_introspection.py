"""
Generates a static schema-reference document for the AI/agentic layer —
Layer 1 (auto-generated structural facts) of the two-layer grounding
design. Run manually whenever the graph schema changes (a new
_load_*_edges function added to loader.py, a relationship renamed,
etc.), NOT on every agent request — same "pull once, reuse" philosophy
as everything else in this project. See docs/graph_schema_reference.md
for Layer 2 (hand-written semantics) that lives alongside this file's
output.
"""
from __future__ import annotations

from neo4j import Driver


def _get_labels(driver: Driver) -> list[str]:
    with driver.session() as session:
        result = session.run("CALL db.labels() YIELD label RETURN label ORDER BY label")
        return [r["label"] for r in result]


def _get_relationship_types(driver: Driver) -> list[str]:
    with driver.session() as session:
        result = session.run(
            "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType ORDER BY relationshipType"
        )
        return [r["relationshipType"] for r in result]


def _get_node_properties(driver: Driver) -> dict[str, list[tuple[str, str]]]:
    """Returns {label: [(propertyName, propertyType), ...]}."""
    with driver.session() as session:
        result = session.run(
            """
            CALL db.schema.nodeTypeProperties()
            YIELD nodeType, propertyName, propertyTypes
            RETURN nodeType, propertyName, propertyTypes
            ORDER BY nodeType, propertyName
            """
        )
        by_label: dict[str, list[tuple[str, str]]] = {}
        for r in result:
            # nodeType comes back like ":`Rule`" -- strip the decoration
            label = r["nodeType"].strip(":`")
            types = ",".join(r["propertyTypes"]) if r["propertyTypes"] else "unknown"
            by_label.setdefault(label, []).append((r["propertyName"], types))
        return by_label


def _get_rel_properties(driver: Driver) -> dict[str, list[tuple[str, str]]]:
    """Returns {relType: [(propertyName, propertyType), ...]}."""
    with driver.session() as session:
        result = session.run(
            """
            CALL db.schema.relTypeProperties()
            YIELD relType, propertyName, propertyTypes
            RETURN relType, propertyName, propertyTypes
            ORDER BY relType, propertyName
            """
        )
        by_type: dict[str, list[tuple[str, str]]] = {}
        for r in result:
            rel_type = r["relType"].strip(":`")
            types = ",".join(r["propertyTypes"]) if r["propertyTypes"] else "unknown"
            by_type.setdefault(rel_type, []).append((r["propertyName"], types))
        return by_type


def _get_topology(driver: Driver) -> list[tuple[str, str, str]]:
    """Returns [(source_label, rel_type, target_label), ...] via a
    sample-based query (MATCH + DISTINCT), since db.schema.visualization()
    returns a graph-shaped result that's awkward to flatten cleanly —
    this is more directly usable for a text reference."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (a)-[r]->(b)
            RETURN DISTINCT labels(a) AS source_labels, type(r) AS rel_type, labels(b) AS target_labels
            ORDER BY rel_type
            """
        )
        return [
            (":".join(r["source_labels"]), r["rel_type"], ":".join(r["target_labels"]))
            for r in result
        ]


def generate_schema_reference(driver: Driver) -> str:
    """Builds the full Layer 1 markdown document from live introspection."""
    labels = _get_labels(driver)
    rel_types = _get_relationship_types(driver)
    node_props = _get_node_properties(driver)
    rel_props = _get_rel_properties(driver)
    topology = _get_topology(driver)

    lines = ["# Graph Schema Reference (auto-generated — do not hand-edit)", ""]

    lines.append("## Node labels")
    for label in labels:
        lines.append(f"- {label}")
    lines.append("")

    lines.append("## Node properties")
    for label in labels:
        props = node_props.get(label, [])
        if not props:
            continue
        lines.append(f"**{label}**")
        for name, ptype in props:
            lines.append(f"- {name}: {ptype}")
        lines.append("")

    lines.append("## Relationship types")
    for rel in rel_types:
        lines.append(f"- {rel}")
    lines.append("")

    lines.append("## Relationship properties")
    for rel in rel_types:
        props = rel_props.get(rel, [])
        if not props:
            lines.append(f"**{rel}**: (no properties)")
            continue
        lines.append(f"**{rel}**")
        for name, ptype in props:
            lines.append(f"- {name}: {ptype}")
        lines.append("")

    lines.append("## Topology (source -> relationship -> target)")
    for source, rel, target in topology:
        lines.append(f"- ({source}) -[:{rel}]-> ({target})")
    lines.append("")

    return "\n".join(lines)