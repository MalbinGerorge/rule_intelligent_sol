"""
Builds the full picture of ONE rule for the Rule Analyzer.

Multiple formatting approaches exist here, in the order they were
built and superseded:
  - fetch_rule_chain (Neo4j, via graph_query.py): good for graph
    traversal questions (dependents, MITRE, etc.) -- same functions
    already powering UI2.
  - fetch_sequential_chain (Postgres, via rule_conditions directly):
    TRUE execution order for one rule/BB alone, no dependency
    traversal.
  - fetch_full_chain_with_dependencies / format_full_chain_for_llm:
    BFS traversal + a separate "dependencies" appendix, with parent
    labels. SUPERSEDED by format_full_chain_inline below -- kept for
    reference, not the recommended entry point anymore.
  - format_full_chain_inline: the RECOMMENDED entry point. DFS,
    renders each referenced BB's logic INLINE at the exact point it's
    referenced (like a function call pausing to run the callee, then
    resuming) -- matches QRadar's real nested-AND semantics directly.
    Includes each rule/BB's own RESPONSE/ACTIONS and ENABLED/DISABLED
    status. The ROOT rule's own identifier is now ALSO shown
    explicitly -- CONFIRMED NECESSARY from a real bug: investigation
    tools need an identifier to look a rule/BB up by, and the root
    rule's identifier was never rendered anywhere, causing the LLM to
    guess a wrong value (0) when trying to call a tool on itself.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections import deque

from neo4j import Session as Neo4jSession
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import graph_query


def fetch_rule_chain(session: Neo4jSession, rule_id: int) -> dict | None:
    """Returns the same shape UI2's /graph/rules/{id} endpoint returns,
    or None if the rule doesn't exist in the graph."""
    rule = graph_query.get_rule_node(session, rule_id)
    if rule is None:
        return None

    return {
        "rule": rule,
        "references": graph_query.get_rule_references(session, rule_id),
        "conditions": graph_query.get_rule_conditions(session, rule_id),
        "log_sources": graph_query.get_rule_logsources(session, rule_id),
        "mitre": graph_query.get_rule_mitre(session, rule_id),
        "followed_by": graph_query.get_rule_followed_by(session, rule_id),
    }


def format_rule_chain_for_llm(chain: dict) -> str:
    """Turns the fetched chain into a clean, readable text block --
    NOT raw JSON dumped at the model. Structure and plain language over
    a wall of nested brackets, same reasoning as why raw_text exists
    on Condition nodes in the first place."""
    rule = chain["rule"]
    lines = [
        f"RULE: {rule.get('name')}",
        f"  Identifier: {rule.get('identifier')}",
        f"  Type: {rule.get('object_type')} | Enabled: {rule.get('enabled')}",
        "",
    ]

    if chain["log_sources"]:
        lines.append("REQUIRED LOG SOURCE TYPE(S):")
        for ls in chain["log_sources"]:
            lines.append(f"  - {ls}")
        lines.append("")
    else:
        lines.append("REQUIRED LOG SOURCE TYPE(S): none specified")
        lines.append("")

    if chain["references"]:
        lines.append("REFERENCED BUILDING BLOCKS:")
        for ref in chain["references"]:
            threshold = ref.get("threshold") or {}
            if threshold.get("threshold_count"):
                lines.append(
                    f"  - {ref.get('name')} (identifier: {ref.get('identifier')}) "
                    f"-- must match {threshold.get('threshold_count')}x "
                    f"within {threshold.get('threshold_time_value')} {threshold.get('threshold_time_unit')}, "
                    f"grouped by {threshold.get('threshold_grouping_field')}"
                )
            else:
                lines.append(f"  - {ref.get('name')} (identifier: {ref.get('identifier')}) -- plain reference")
        lines.append("")
    else:
        lines.append("REFERENCED BUILDING BLOCKS: none")
        lines.append("")

    if chain["conditions"]:
        lines.append("CONDITIONS (in order):")
        for c in chain["conditions"]:
            negated = " [NEGATED]" if c.get("negated") else ""
            lines.append(f"  - {c.get('raw_text') or c.get('test_class')}{negated}")
        lines.append("")
    else:
        lines.append("CONDITIONS: none standalone -- logic is entirely composed via referenced building blocks above")
        lines.append("")

    if chain["mitre"]:
        lines.append("MITRE ATT&CK MAPPING:")
        for m in chain["mitre"]:
            tactic = f" (tactic: {m.get('tactic_name')})" if m.get("tactic_name") else ""
            lines.append(f"  - {m.get('technique_id')} {m.get('technique_name')}{tactic}")
        lines.append("")

    if chain["followed_by"]:
        lines.append("SEQUENCE RELATIONSHIPS THIS RULE DEFINES:")
        for f in chain["followed_by"]:
            rel = f.get("relationship") or {}
            time_info = f" within {rel.get('time_value')} {rel.get('time_unit')}" if rel.get("time_value") else ""
            lines.append(f"  - {f.get('source_name')} -> {f.get('target_name')}{time_info}")
        lines.append("")

    return "\n".join(lines)


def fetch_sequential_chain(db: Session, rule_id: int) -> list[dict] | None:
    """Pulls EVERY test for this rule from Postgres's rule_conditions,
    in TRUE original XML order (sequence_order), regardless of which
    Neo4j node/edge type it eventually became. Returns None if the
    rule has no rows at all (doesn't exist, or genuinely has zero
    conditions parsed -- caller should distinguish via a separate rule
    existence check if that matters)."""
    rows = db.execute(
        text(
            """
            SELECT test_class, negated, raw_text, structured_data
            FROM rule_conditions
            WHERE rule_id = :rule_id
            ORDER BY sequence_order
            """
        ),
        {"rule_id": rule_id},
    ).mappings().all()

    if not rows:
        return None

    return [
        {
            "test_class": r["test_class"],
            "negated": r["negated"],
            "raw_text": r["raw_text"],
            "structured_data": r["structured_data"] if isinstance(r["structured_data"], dict) else json.loads(r["structured_data"]),
        }
        for r in rows
    ]


def fetch_rule_response(db: Session, rule_id: int) -> dict | None:
    """Fetches the rule_responses row for one rule -- offense
    creation/naming, event dispatch, reference writes, limiter.
    Returns None if the rule has no <responses> at all (common for
    BBs, which typically don't dispatch anything independently -- but
    checked for every rule/BB anyway, not assumed)."""
    row = db.execute(
        text("SELECT * FROM rule_responses WHERE rule_id = :rule_id"),
        {"rule_id": rule_id},
    ).mappings().first()
    return dict(row) if row is not None else None


def format_rule_response_for_llm(resp: dict) -> list[str]:
    """Renders one rule's response/action data as readable lines --
    CONFIRMED NECESSARY from a real gap: a rule's CONDITIONS can be
    100% structurally correct and still never produce a visible
    offense, if force_offense_creation is false and nothing else
    creates one. Without this section, the LLM has no way to see that
    -- it only ever saw what triggers the logic, never what happens
    once it does."""
    lines = ["  [RESPONSE / ACTIONS once the above matches:]"]

    if resp.get("event_name"):
        lines.append(
            f"    Dispatches new event: \"{resp['event_name']}\" "
            f"(severity {resp.get('severity')}, credibility {resp.get('credibility')}, "
            f"relevance {resp.get('relevance')})"
        )

    if resp.get("force_offense_creation") is True:
        lines.append("    Offense creation: FORCED -- this WILL create a new offense if none exists yet")
    elif resp.get("force_offense_creation") is False:
        lines.append(
            "    Offense creation: NOT FORCED -- WARNING: even if every condition above matches "
            "perfectly, this rule will NOT independently create a visible offense unless "
            "another mechanism does (e.g. contribute_offense_name, or another rule)"
        )

    if resp.get("offense_mapping") is not None:
        lines.append(
            f"    Offense grouped by: property #{resp['offense_mapping']} "
            "(raw QRadar field index, not yet resolved to a field name)"
        )

    if resp.get("limiter_response_count") is not None:
        lines.append(
            f"    Response limiter: at most {resp['limiter_response_count']} response(s) "
            f"per {resp.get('limiter_interval_count')} {resp.get('limiter_interval_type')} "
            f"per {resp.get('limiter_host_type')}"
        )

    if resp.get("ref_write_target_name"):
        lines.append(
            f"    Writes to reference data: \"{resp['ref_write_target_name']}\" "
            f"(key: {resp.get('ref_write_key_field')}, type: {resp.get('ref_write_type')})"
        )

    return lines


def fetch_rule_scope(db: Session, rule_id: int) -> str | None:
    """Reads the rule's own <rule scope="LOCAL|GLOBAL"> attribute from
    raw_json's stored rule_xml. CONFIRMED NECESSARY from a real gap:
    every real QRadar rule's logic starts with "APPLY {name} on events
    which are detected by the {scope} system" -- this is NOT a <test>
    element, so it was never captured in rule_conditions at all, and
    was entirely missing from the reconstructed sequence. No new
    column needed -- rule_xml is already stored; this just reads an
    attribute from it that was never read before."""
    row = db.execute(
        text("SELECT raw_json FROM rules WHERE id = :rule_id"), {"rule_id": rule_id}
    ).mappings().first()
    if row is None or not row["raw_json"]:
        return None

    data = row["raw_json"] if isinstance(row["raw_json"], dict) else json.loads(row["raw_json"])
    rule_xml = data.get("rule_xml")
    if not rule_xml:
        return None

    try:
        root = ET.fromstring(rule_xml)
    except ET.ParseError:
        return None

    return root.get("scope")


def format_sequential_chain_for_llm(rule_name: str, scope: str | None, chain: list[dict]) -> str:
    """Renders the TRUE sequence as QRadar itself would show it.

    CONFIRMED bug fix: "APPLY" is reserved for the rule's own scope
    line ("APPLY {name} on events which are detected by the {scope}
    system") -- confirmed from real data this line is ALWAYS present
    and ALWAYS first, in every rule, regardless of what its first
    actual condition is. Every condition in the chain (including the
    first one) uses "AND"/"AND NOT" -- never "APPLY"."""
    scope_label = scope or "LOCAL"
    lines = [
        f"RULE: {rule_name}",
        "",
        "LOGIC (in the exact order QRadar evaluates it):",
        f"  APPLY {rule_name} on events which are detected by the {scope_label} system",
    ]
    for c in chain:
        prefix = "AND NOT" if c["negated"] else "AND"
        text_part = c["raw_text"] or f"[{c['test_class']}]"
        lines.append(f"  {prefix} {text_part}")
    return "\n".join(lines)


def get_referenced_bb_ids(db: Session, rule_id: int) -> list[str]:
    """Which BB identifiers does this rule reference, per the already-
    tested rule_building_blocks table (populated by
    rule_xml_parser.extract_bb_references -- captures every
    method="...Rules" reference, regardless of which test class it
    came from). This is the authoritative source for traversal, not
    something re-derived from rule_conditions' varied structured_data
    shapes."""
    rows = db.execute(
        text("SELECT DISTINCT bb_id FROM rule_building_blocks WHERE rule_id = :rule_id"),
        {"rule_id": rule_id},
    ).fetchall()
    return [r[0] for r in rows]


def resolve_identifier_to_rule_id(db: Session, customer_id: int, identifier: str) -> int | None:
    return db.execute(
        text("SELECT id FROM rules WHERE identifier = :identifier AND customer_id = :customer_id"),
        {"identifier": identifier, "customer_id": customer_id},
    ).scalar_one_or_none()


def fetch_full_chain_with_dependencies(
    db: Session, customer_id: int, root_rule_id: int, max_depth: int = 5
) -> dict | None:
    """
    SUPERSEDED by format_full_chain_inline -- kept for reference. BFS
    traversal producing a flat "dependencies" list with parent labels,
    rendered as a separate appendix by format_full_chain_for_llm.
    """
    root_row = db.execute(
        text("SELECT name FROM rules WHERE id = :id"), {"id": root_rule_id}
    ).mappings().first()
    if root_row is None:
        return None

    visited: set[int] = set()
    queue = deque([(root_rule_id, 0, None, None)])
    root_entry: dict | None = None
    dependencies: list[dict] = []

    while queue:
        current_rule_id, depth, parent_name, parent_identifier = queue.popleft()
        if current_rule_id in visited:
            continue
        visited.add(current_rule_id)

        rule_row = db.execute(
            text("SELECT identifier, name FROM rules WHERE id = :id"), {"id": current_rule_id}
        ).mappings().first()
        if rule_row is None:
            continue

        scope = fetch_rule_scope(db, current_rule_id)
        chain = fetch_sequential_chain(db, current_rule_id) or []

        entry = {
            "rule_id": current_rule_id,
            "identifier": rule_row["identifier"],
            "name": rule_row["name"],
            "scope": scope,
            "chain": chain,
            "depth": depth,
            "parent_name": parent_name,
            "parent_identifier": parent_identifier,
        }

        if depth == 0:
            root_entry = entry
        else:
            dependencies.append(entry)

        if depth >= max_depth:
            continue

        for bb_id in get_referenced_bb_ids(db, current_rule_id):
            next_rule_id = resolve_identifier_to_rule_id(db, customer_id, bb_id)
            if next_rule_id is not None and next_rule_id not in visited:
                queue.append((next_rule_id, depth + 1, rule_row["name"], rule_row["identifier"]))

    return {"root": root_entry, "dependencies": dependencies}


def format_full_chain_for_llm(full_chain: dict) -> str:
    """SUPERSEDED by format_full_chain_inline -- kept for reference."""
    root = full_chain["root"]
    lines = [format_sequential_chain_for_llm(root["name"], root["scope"], root["chain"])]

    if full_chain["dependencies"]:
        lines.append("")
        lines.append("=" * 60)
        lines.append("REFERENCED BUILDING BLOCK LOGIC")
        lines.append("IMPORTANT: this is a NESTED requirement tree, NOT a sequence of")
        lines.append("steps that run one after another. The root rule fires only if its")
        lines.append("own conditions above ALL match, AND every building block it")
        lines.append("references below ALSO has ALL of its own conditions match --")
        lines.append("including whatever THAT building block itself references, and so on.")
        lines.append("Each entry below states which rule/BB references it directly.")
        lines.append("=" * 60)
        for dep in full_chain["dependencies"]:
            indent = "  " * dep["depth"]
            lines.append("")
            lines.append(
                f"{indent}--- {dep['name']} (identifier: {dep['identifier']}) "
                f"-- REFERENCED BY: {dep['parent_name']} (identifier: {dep['parent_identifier']}) ---"
            )
            if not dep["chain"]:
                lines.append(f"{indent}  (no standalone conditions parsed for this building block)")
                continue
            for c in dep["chain"]:
                prefix = "AND NOT" if c["negated"] else "AND"
                text_part = c["raw_text"] or f"[{c['test_class']}]"
                lines.append(f"{indent}  {prefix} {text_part}")

    return "\n".join(lines)


def _extract_bb_ids_from_structured_data(structured_data: dict) -> list[str]:
    """Every place a condition can reference BB(s), across all the
    structural shapes confirmed in rule_condition_parser.py. A given
    condition matches none of these when it's a plain field check
    (e.g. ArielFilterTest never references a BB)."""
    bb_ids: list[str] = []
    if "rule_match" in structured_data:
        bb_ids += structured_data["rule_match"].get("bb_ids", [])
    if "threshold" in structured_data:
        bb_ids += structured_data["threshold"].get("bb_ids", [])
    if "sequence" in structured_data:
        bb_ids += structured_data["sequence"].get("bb_ids", [])
    if "double_sequence" in structured_data:
        ds = structured_data["double_sequence"]
        bb_ids += ds.get("stage1_bb_ids", []) + ds.get("stage2_bb_ids", [])
    if "cause_and_effect" in structured_data:
        cae = structured_data["cause_and_effect"]
        bb_ids += cae.get("stage1_bb_ids", []) + cae.get("stage2_bb_ids", [])
    if "trigger_match_count" in structured_data:
        tmc = structured_data["trigger_match_count"]
        bb_ids += tmc.get("trigger_bb_ids", []) + tmc.get("later_bb_ids", [])
    return bb_ids


def _format_chain_recursive(
    db: Session,
    customer_id: int,
    rule_id: int,
    visited: frozenset[int],
    depth: int = 0,
    max_depth: int = 5,
) -> list[str]:
    """DFS, INLINE: walks this rule/BB's own conditions in true order;
    whenever a condition references a BB, recursively renders that
    BB's full logic IMMEDIATELY, right there, before continuing to the
    next condition -- exactly like a function call pausing, running
    the callee fully, then resuming at the next line. visited is
    passed by VALUE (frozenset), not mutated in place, so two
    unrelated branches of the tree can each independently reference
    the same BB without falsely tripping the other's cycle guard --
    only a genuine cycle back to an ANCESTOR on this exact path is
    blocked."""
    if rule_id in visited or depth > max_depth:
        return [f"{'  ' * depth}[cyclic or too-deep reference, stopped here]"]
    visited = visited | {rule_id}

    rule_row = db.execute(
        text("SELECT identifier, name, enabled FROM rules WHERE id = :id"), {"id": rule_id}
    ).mappings().first()
    if rule_row is None:
        return [f"{'  ' * depth}[referenced rule/BB not found]"]

    chain = fetch_sequential_chain(db, rule_id) or []
    indent = "  " * depth
    lines: list[str] = []
    enabled_tag = "ENABLED" if rule_row["enabled"] else "*** DISABLED ***"

    if depth == 0:
        scope = fetch_rule_scope(db, rule_id) or "LOCAL"
        lines.append(
            f"{indent}APPLY {rule_row['name']} (identifier: {rule_row['identifier']}) [{enabled_tag}] "
            f"on events which are detected by the {scope} system"
        )
    else:
        lines.append(
            f"{indent}[requires ALL of the following from {rule_row['name']} "
            f"(identifier: {rule_row['identifier']}, status: {enabled_tag}) to ALSO match:]"
        )

    for c in chain:
        prefix = "AND NOT" if c["negated"] else "AND"
        text_part = c["raw_text"] or f"[{c['test_class']}]"
        lines.append(f"{indent}  {prefix} {text_part}")

        for bb_id in _extract_bb_ids_from_structured_data(c["structured_data"]):
            next_rule_id = resolve_identifier_to_rule_id(db, customer_id, bb_id)
            if next_rule_id is not None:
                lines.extend(
                    _format_chain_recursive(db, customer_id, next_rule_id, visited, depth + 1, max_depth)
                )

    response = fetch_rule_response(db, rule_id)
    if response is not None:
        for line in format_rule_response_for_llm(response):
            lines.append(f"{indent}{line}")

    return lines


def format_full_chain_inline(db: Session, customer_id: int, rule_id: int) -> str | None:
    """The RECOMMENDED entry point for LLM context: renders the FULL
    nested AND-tree inline, in one continuous read, matching how
    nested boolean logic (or a call stack) actually reads -- not a
    flat root-chain-plus-appendix. Includes each rule/BB's own
    RESPONSE/ACTIONS and ENABLED/DISABLED status. Returns None if the
    rule doesn't exist."""
    rule_row = db.execute(
        text("SELECT name FROM rules WHERE id = :id"), {"id": rule_id}
    ).mappings().first()
    if rule_row is None:
        return None

    lines = _format_chain_recursive(db, customer_id, rule_id, visited=frozenset())
    header = (
        f"RULE: {rule_row['name']}\n\n"
        "LOGIC (nested -- each '[requires ALL of the following...]' block\n"
        "must ALSO fully match for the line that introduced it to be satisfied):\n"
    )
    return header + "\n".join(lines)