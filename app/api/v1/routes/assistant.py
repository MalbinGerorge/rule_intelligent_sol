"""
AI agent API — natural language question -> Cypher -> graph results.
Thin HTTP layer only; all real logic lives in app/ai/agents/assistant/.
"""

from __future__ import annotations

from fastapi import APIRouter
from neo4j import Driver

from app.ai.agents.assistant.service import ask_graph
from app.api.v1.schemas.assistant import AgentAskRequest, AgentAskResponse
from app.integrations.neo4j.client import get_driver

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/ask", response_model=AgentAskResponse)
def ask(request: AgentAskRequest) -> AgentAskResponse:
    driver: Driver = get_driver()
    result = ask_graph(driver, request.question, request.customer_id)
    return AgentAskResponse(**result)
