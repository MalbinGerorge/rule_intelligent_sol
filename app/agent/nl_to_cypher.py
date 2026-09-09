"""
Prompt construction + response parsing for the NL-to-Cypher agent.
Pure, reusable logic — the actual LLM call and orchestration now live
in app/agent/agent_nodes.py (LangGraph), which imports from here.
"""
from __future__ import annotations

import re
from pathlib import Path

_DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "docs"

_FEW_SHOT_EXAMPLES = """
EXAMPLES:

Question: "Which rules check the Command field?"
Cypher: MATCH (r:Rule {customer_id: $customer_id})-[:HAS_CONDITION]->(c:Condition {field: "Command"}) WHERE NOT r.is_superseded RETURN r.name, c.operator, c.values

Question: "Which rules depend on the building block SYSTEM-1300?"
Cypher: MATCH (r:Rule {customer_id: $customer_id})-[rel:REFERENCES]->(bb:Rule {identifier: "SYSTEM-1300", customer_id: $customer_id}) WHERE NOT r.is_superseded RETURN r.name, properties(rel) AS reference_info

Question: "Which rules detect MITRE technique T1078?"
Cypher: MATCH (r:Rule {customer_id: $customer_id})-[:DETECTS_TECHNIQUE]->(t:MitreTechnique {technique_id: "T1078"}) WHERE NOT r.is_superseded RETURN r.name

Question: "What's currently inside the TOR Relay Nodes reference set?"
Cypher: NOT_ANSWERABLE: Reference set contents are never stored in this graph — only which rules structurally depend on the set, via DEPENDS_ON_REFSET, is available here.

Question: "Which rules use a threshold of more than 100?"
Cypher: MATCH (r:Rule {customer_id: $customer_id})-[rel:REFERENCES]->(bb) WHERE NOT r.is_superseded AND rel.threshold_count > 100 RETURN r.name, rel.threshold_count, bb.name

Question: "Show me the risky rules."
Cypher: CLARIFY: "Risky" isn't a defined concept in this graph — do you mean rules that are currently disabled, rules with no MITRE technique mapped, rules referencing a specific reference set, or something else?
"""


def _load_grounding_context() -> str:
    schema = (_DOCS_DIR / "graph_schema_reference.md").read_text(encoding="utf-8")
    semantics = (_DOCS_DIR / "graph_semantics_reference.md").read_text(encoding="utf-8")
    return f"{schema}\n\n{semantics}"


def build_system_prompt() -> str:
    grounding = _load_grounding_context()
    return f"""You are a Cypher query generator for a QRadar rule intelligence graph database (Neo4j).

{grounding}

{_FEW_SHOT_EXAMPLES}

INSTRUCTIONS:
- Generate ONLY a single, valid, READ-ONLY Cypher query (MATCH/RETURN/WHERE/OPTIONAL MATCH/WITH/ORDER BY/LIMIT) that answers the question.
- NEVER generate CREATE, MERGE, DELETE, SET, REMOVE, or DROP under any circumstances.
- Always scope Rule/Condition/etc. matches by customer_id: $customer_id — the actual value is supplied as a query parameter, do not hardcode a number.
- Always exclude superseded rules: every query matching (:Rule) must include "WHERE NOT r.is_superseded" (or "AND NOT r.is_superseded" if a WHERE clause already exists) — a customer-overridden rule leaves a stale duplicate node behind for structural completeness, and it must never be counted or returned.
- Return ONLY the raw Cypher query text. No markdown code fences, no explanation, no commentary.
- If the question genuinely cannot be answered from this graph (see Layer 2's "never stored here" notes — e.g. reference set/map CONTENTS), respond with exactly one line: NOT_ANSWERABLE: <brief reason>. Do not attempt a query that will just return nothing.
- If the question is too AMBIGUOUS to translate into one specific query (e.g. it uses a vague term like "risky" or "important" that has no defined meaning in this schema, or could reasonably mean two different things), respond with exactly one line: CLARIFY: <a specific question to ask the user>. Do not guess at an interpretation and generate a query anyway.
- NEVER return a raw node or relationship variable directly (e.g. "RETURN rel" or "RETURN r"). Always return specific properties (e.g. "RETURN r.name") or use properties(rel)/properties(r) to get a plain map — raw graph objects cannot be serialized in the response."""
def strip_code_fences(text: str) -> str:
    """LLMs often wrap Cypher in ```cypher ... ``` despite instructions
    not to. Strip that off if present; otherwise return unchanged."""
    stripped = text.strip()
    fence_match = re.match(r"^```(?:cypher)?\s*\n?(.*?)\n?```$", stripped, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    return stripped


def parse_llm_response(raw: str) -> dict:
    """
    Parses the LLM's raw text response into one of three outcomes:
        {"kind": "query", "query": "<cypher>"}
        {"kind": "not_answerable", "reason": "<why not>"}
        {"kind": "clarify", "question": "<question to ask the user>"}
    """
    cleaned = strip_code_fences(raw)

    if cleaned.startswith("NOT_ANSWERABLE:"):
        return {"kind": "not_answerable", "reason": cleaned[len("NOT_ANSWERABLE:"):].strip()}

    if cleaned.startswith("CLARIFY:"):
        return {"kind": "clarify", "question": cleaned[len("CLARIFY:"):].strip()}

    return {"kind": "query", "query": cleaned}