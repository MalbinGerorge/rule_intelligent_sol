"""
Graph STRUCTURE for the Rule Analyzer's investigation loop -- which
nodes exist, how they connect, and the routing/conditional-edge logic
that decides where to go next. Node LOGIC (what each step actually
does, the 6 tools, the prompts) lives in investigation_nodes.py; this
file only wires things together.

Genuinely dynamic -- unlike the Q&A agent's fixed generate->validate
pipeline, HERE the LLM decides which tools to call, how many, and in
what order, based on what its own initial structural analysis already
flagged. This is exactly the case that justifies LangGraph's
machinery, as distinct from chain_analysis.py's single straight-line
call.

Bounded by MAX_ITERATIONS, same principle as the Q&A agent's
MAX_RETRIES -- never an unbounded loop, confirmed via test.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from app.rule_analyzer.investigation_nodes import build_nodes
from app.rule_analyzer.investigation_state import InvestigationState
from app.rule_analyzer.llm_provider import LLMProvider
from app.services.qradar_client import QRadarClient
from app.rule_analyzer.report_renderer import render_report


MAX_ITERATIONS = 4


def route_after_analyze(state: InvestigationState) -> str:
    return "end" if state.get("final_report") else "investigate"


def route_after_investigate(state: InvestigationState) -> str:
    last_message = state["messages"][-1]
    has_tool_calls = bool(getattr(last_message, "tool_calls", None))
    if not has_tool_calls or state.get("iterations", 0) >= MAX_ITERATIONS:
        return "synthesize"
    return "execute_tools"


def build_investigation_graph(db: Session, customer_id: int, llm_provider: LLMProvider, qradar_client: QRadarClient):
    nodes = build_nodes(db, customer_id, llm_provider, qradar_client)

    graph = StateGraph(InvestigationState)
    graph.add_node("analyze_chain", nodes["analyze_chain"])
    graph.add_node("investigate", nodes["investigate"])
    graph.add_node("execute_tools", nodes["execute_tools"])
    graph.add_node("synthesize_report", nodes["synthesize_report"])

    graph.set_entry_point("analyze_chain")
    graph.add_conditional_edges("analyze_chain", route_after_analyze, {"investigate": "investigate", "end": END})
    graph.add_conditional_edges(
        "investigate", route_after_investigate, {"execute_tools": "execute_tools", "synthesize": "synthesize_report"}
    )
    graph.add_edge("execute_tools", "investigate")
    graph.add_edge("synthesize_report", END)

    return graph.compile()


def format_investigation_trace(messages: list[BaseMessage]) -> str:
    """Renders the full reasoning path -- every LLM decision to call a
    tool (with its exact arguments), every tool result, in order --
    as a compact, readable log. Built specifically for prompt/harness
    tuning: lets a human see EXACTLY why the agent reached its
    conclusion, not just the final report. Uses data already present
    in state["messages"] -- nothing new is tracked, this just makes
    what's already there visible."""
    lines = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            lines.append("[SYSTEM] Initial context (rule chain + structural analysis) provided.")
        elif isinstance(msg, AIMessage):
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    lines.append(f"[LLM -> tool call] {tc['name']}({tc['args']})")
            elif msg.content:
                lines.append(f"[LLM] {msg.content}")
        elif isinstance(msg, ToolMessage):
            content_preview = str(msg.content)
            if len(content_preview) > 2000:
                content_preview = content_preview[:2000] + "... (truncated)"
            lines.append(f"[TOOL RESULT] {content_preview}")
        elif isinstance(msg, HumanMessage):
            lines.append(f"[REPORT REQUEST] {msg.content}")
    return "\n".join(lines)


# def run_investigation(
#     db: Session, llm_provider: LLMProvider, qradar_client: QRadarClient, customer_id: int, rule_id: int
# ) -> dict:
#     graph = build_investigation_graph(db, customer_id, llm_provider, qradar_client)
#     final_state = graph.invoke({"rule_id": rule_id, "customer_id": customer_id})
#     messages = final_state.get("messages", [])
#     tool_calls_made = sum(len(getattr(m, "tool_calls", None) or []) for m in messages)
#     return {
#         "chain_analysis": final_state.get("chain_analysis"),
#         "final_report": final_state.get("final_report"),
#         "tool_calls_made": tool_calls_made,
#         "trace": format_investigation_trace(messages),
#     }


def run_investigation(
    db: Session, llm_provider: LLMProvider, qradar_client: QRadarClient, customer_id: int, rule_id: int
) -> dict:
    graph = build_investigation_graph(db, customer_id, llm_provider, qradar_client)
    final_state = graph.invoke({"rule_id": rule_id, "customer_id": customer_id})
    messages = final_state.get("messages", [])
    tool_calls_made = sum(len(getattr(m, "tool_calls", None) or []) for m in messages)
    report_obj = final_state.get("final_report")
    return {
        "chain_analysis": final_state.get("chain_analysis"),
        "final_report": render_report(report_obj) if report_obj else None,
        "final_report_structured": report_obj,  # raw object, useful later for the Postgres history table
        "tool_calls_made": tool_calls_made,
        "trace": format_investigation_trace(messages),
    }