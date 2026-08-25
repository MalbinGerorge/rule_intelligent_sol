"""
LangGraph state schema for the NL-to-Cypher agent graph. Kept as a
plain TypedDict — LangGraph's convention — not a Pydantic model, so it
stays a plain serializable dict as it flows node to node.
"""
from __future__ import annotations

from typing import TypedDict

from langchain_core.messages import BaseMessage


class AgentState(TypedDict, total=False):
    question: str
    customer_id: int
    messages: list[BaseMessage]  # conversation history, grows on retry

    query: str | None
    error: str | None
    retry_count: int

    status: str | None  # "ok" | "needs_clarification" | "not_answerable" | "rejected"
    rows: list[dict] | None
    clarification: str | None
    not_answerable_reason: str | None