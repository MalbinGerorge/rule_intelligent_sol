"""
Entry point the API layer calls. Builds the LangGraph agent graph for
this request, invokes it, and maps the final state into the same flat
response shape the API has always used — the API endpoint doesn't need
to know whether the orchestration underneath is a manual loop or a
LangGraph graph.
"""
from __future__ import annotations

from neo4j import Driver

from app.agent.agent_nodes import build_agent_graph


def ask_graph(driver: Driver, question: str, customer_id: int) -> dict:
    """
    Returns one of:
        {"status": "needs_clarification", "question": "..."}
        {"status": "not_answerable", "reason": "..."}
        {"status": "rejected", "query": "...", "error": "..."}
        {"status": "ok", "query": "...", "rows": [...], "retried": bool}
        {"status": "llm_error", "error": "..."}
    """
    try:
        graph = build_agent_graph(driver)
        final_state = graph.invoke({
            "question": question,
            "customer_id": customer_id,
            "messages": [],
            "retry_count": 0,
        })
    except Exception as e:
        return {"status": "llm_error", "error": str(e)}

    status = final_state.get("status")

    if status == "needs_clarification":
        return {"status": "needs_clarification", "question": final_state["clarification"]}

    if status == "not_answerable":
        return {"status": "not_answerable", "reason": final_state["not_answerable_reason"]}

    if status == "ok":
        return {
            "status": "ok",
            "query": final_state["query"],
            "rows": final_state["rows"],
            "retried": final_state.get("retry_count", 0) > 0,
        }

    # Exhausted retries without success.
    return {
        "status": "rejected",
        "query": final_state.get("query"),
        "error": final_state.get("error"),
    }