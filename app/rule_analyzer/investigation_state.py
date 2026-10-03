"""State schema for the Rule Analyzer's ReAct investigation graph."""
from __future__ import annotations

from typing import TypedDict

from langchain_core.messages import BaseMessage

from app.rule_analyzer.chain_analysis import ChainAnalysis


class InvestigationState(TypedDict, total=False):
    rule_id: int
    customer_id: int

    chain_analysis: ChainAnalysis | None
    formatted_chain: str | None

    messages: list[BaseMessage]
    iterations: int

    final_report: str | None