"""
The first real reasoning step of the Rule Analyzer: GPT-5.2 reads the
formatted rule chain (from rule_chain_context.py) and produces its
initial understanding -- what this rule is meant to detect, and
everything that must structurally be true for it to ever fire. This
becomes the ReAct loop's starting context, not a disconnected summary.

Structured output (a Pydantic model), not free text -- so later steps
(the ReAct loop, final report synthesis) can rely on a guaranteed
shape instead of re-parsing prose.
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.rule_analyzer.llm_provider import LLMProvider
from app.rule_analyzer.rule_chain_context import format_full_chain_inline

_SYSTEM_PROMPT = """You are a senior detection engineering analyst reviewing a QRadar rule's structure.

You are NOT investigating live data yet -- only reasoning from the rule's own definition, exactly as given to you. Do not assume anything about live log source status, DSM parsing, or reference set contents; those are checked separately, later.

Given the rule's full chain (conditions, referenced building blocks, thresholds, required log sources, MITRE mapping), produce:

1. detection_intent: one or two plain-language sentences describing what real-world behavior or threat this rule is designed to catch.

2. preconditions: everything that must structurally be true for this rule to ever fire -- e.g. "The required log source type must be actively sending events", "BB X must itself be enabled and matching", "At least 500 matching events must occur within 1 minute from the same log source". Be specific to THIS rule's actual conditions and thresholds, not generic.

3. structural_flags: anything that looks like an obvious structural problem visible just from this definition alone -- e.g. a referenced building block that is disabled, a threshold that looks unreasonably high or a window that looks unreasonably short, a rule with no MITRE mapping, a negated condition that looks unusually broad. PAY SPECIAL ATTENTION to the "[RESPONSE / ACTIONS...]" section if present: a rule can have perfectly correct detection logic and STILL never produce a visible offense if it says "Offense creation: NOT FORCED" with no other offense mechanism -- this is a real, common, and easily-missed root cause, distinct from the detection logic being wrong. If nothing looks obviously wrong structurally, return an EMPTY list -- do not invent a flag just to have something to report."""


class ChainAnalysis(BaseModel):
    detection_intent: str = Field(description="What real-world threat/behavior this rule is designed to detect")
    preconditions: list[str] = Field(description="Everything that must structurally be true for this rule to fire")
    structural_flags: list[str] = Field(
        default_factory=list,
        description="Obvious structural problems visible from the definition alone; empty if none",
    )


def analyze_rule_chain(llm_provider: LLMProvider, formatted_chain: str) -> ChainAnalysis:
    llm = llm_provider.get_reasoning_llm()
    structured_llm = llm.with_structured_output(ChainAnalysis)
    return structured_llm.invoke(
        [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=formatted_chain),
        ]
    )


def analyze_rule(db: Session, llm_provider: LLMProvider, customer_id: int, rule_id: int) -> ChainAnalysis | None:
    """
    The full first stage, wired end to end:
        rule_id -> format_full_chain_inline (Postgres, DFS, nested
        inline rendering, includes RESPONSE/ACTIONS) -> analyze_rule_chain
        (GPT-5.2, structured output).

    Returns None if the rule doesn't exist.
    """
    formatted = format_full_chain_inline(db, customer_id, rule_id)
    if formatted is None:
        return None

    return analyze_rule_chain(llm_provider, formatted)