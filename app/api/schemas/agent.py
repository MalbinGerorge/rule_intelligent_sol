from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class AgentAskRequest(BaseModel):
    question: str
    customer_id: int


class AgentAskResponse(BaseModel):
    status: str  # "ok" | "needs_clarification" | "not_answerable" | "rejected" | "llm_error"
    query: str | None = None
    rows: list[dict[str, Any]] | None = None
    retried: bool | None = None
    question: str | None = None  # populated when status == "needs_clarification"
    reason: str | None = None
    error: str | None = None