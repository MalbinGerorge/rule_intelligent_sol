"""
LangGraph node functions and graph construction for the NL-to-Cypher
agent. Two nodes, cyclic (generate <-> validate_execute) with a
hard-bounded retry via retry_count in state — same MAX_RETRIES=1
guarantee as before, now expressed as a graph edge condition instead
of a Python for-loop. LangGraph's own recursion_limit is a second,
independent backstop against runaway cycles, on top of our own check —
same defense-in-depth principle used everywhere else in this project.

The safety-critical pieces (cypher_safety.py's validation,
execute_readonly_cypher's read-only enforcement) are UNCHANGED and
imported as-is — no reason to touch tested, working safety logic just
because the orchestration around it changed frameworks.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI
from langgraph.graph import END, StateGraph
from neo4j import Driver

from app.agent.agent_state import AgentState
from app.agent.graph_agent_query import execute_readonly_cypher
from app.agent.nl_to_cypher import build_system_prompt, parse_llm_response
from app.core.config import settings

MAX_RETRIES = 1


def _get_llm() -> AzureChatOpenAI:
    return AzureChatOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
        azure_deployment=settings.azure_openai_deployment,
        temperature=0,
    )


def generate_query_node(state: AgentState) -> AgentState:
    messages = state.get("messages")

    if not messages:
        # First attempt — fresh conversation.
        messages = [
            SystemMessage(content=build_system_prompt()),
            HumanMessage(content=f"Question: {state['question']}"),
        ]
    else:
        # Retry — append the failed query + the real error as new
        # turns, giving the LLM concrete context to fix it.
        messages = messages + [
            AIMessage(content=state["query"]),
            HumanMessage(
                content=(
                    f"That query failed: {state['error']}\n"
                    "Correct it and return ONLY the fixed Cypher query, "
                    "following all the same rules as before."
                )
            ),
        ]

    llm = _get_llm()
    response = llm.invoke(messages)
    parsed = parse_llm_response(response.content)

    new_state: AgentState = {**state, "messages": messages + [AIMessage(content=response.content)]}

    if parsed["kind"] == "clarify":
        new_state["status"] = "needs_clarification"
        new_state["clarification"] = parsed["question"]
    elif parsed["kind"] == "not_answerable":
        new_state["status"] = "not_answerable"
        new_state["not_answerable_reason"] = parsed["reason"]
    else:
        new_state["query"] = parsed["query"]
        new_state["status"] = None  # not yet resolved — needs validate_execute

    return new_state


def route_after_generate(state: AgentState) -> str:
    if state.get("status") in ("needs_clarification", "not_answerable"):
        return "end"
    return "validate_execute"


def route_after_validate(state: AgentState) -> str:
    if state.get("status") == "ok":
        return "end"
    if state.get("retry_count", 0) > MAX_RETRIES:
        return "end"
    return "generate_query"


def build_agent_graph(driver: Driver):
    """driver is captured via closure in validate_execute_node — kept
    OUT of state, since state should stay a plain, serializable dict,
    not carry a live DB connection."""

    def validate_execute_node(state: AgentState) -> AgentState:
        result = execute_readonly_cypher(
            driver, state["query"], {"customer_id": state["customer_id"]}
        )
        if result["ok"]:
            return {**state, "status": "ok", "rows": result["rows"]}
        return {
            **state,
            "error": result["error"],
            "retry_count": state.get("retry_count", 0) + 1,
        }

    graph = StateGraph(AgentState)
    graph.add_node("generate_query", generate_query_node)
    graph.add_node("validate_execute", validate_execute_node)
    graph.set_entry_point("generate_query")
    graph.add_conditional_edges(
        "generate_query", route_after_generate, {"validate_execute": "validate_execute", "end": END}
    )
    graph.add_conditional_edges(
        "validate_execute", route_after_validate, {"generate_query": "generate_query", "end": END}
    )
    return graph.compile()