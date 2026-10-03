"""
AI agent API — natural language question -> Cypher -> graph results.
Thin HTTP layer only; all real logic lives in app/agent/*.
"""
from __future__ import annotations

from fastapi import APIRouter
from neo4j import Driver

from app.agent.agent_query_service import ask_graph
from app.api.schemas.agent import AgentAskRequest, AgentAskResponse
from app.graph.client import get_driver

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/ask", response_model=AgentAskResponse)
def ask(request: AgentAskRequest) -> AgentAskResponse:
    driver: Driver = get_driver()
    result = ask_graph(driver, request.question, request.customer_id)
    return AgentAskResponse(**result)