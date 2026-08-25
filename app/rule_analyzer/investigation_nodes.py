"""
Node LOGIC for the Rule Analyzer's investigation graph -- what happens
at each step. Graph STRUCTURE (which nodes exist, how they connect,
routing logic) lives in investigation_graph.py; this file is purely
the implementation each node executes when the graph reaches it.
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from sqlalchemy.orm import Session

from app.rule_analyzer.aql_prompt_templates import AQL_TOOL_DESCRIPTION
from app.rule_analyzer.chain_analysis import analyze_rule_chain
from app.rule_analyzer.investigation_state import InvestigationState
from app.rule_analyzer.investigation_tools import (
    check_log_source_status,
    check_reference_data_dependencies,
    check_reference_set_contents,
    check_rule_timing,
    get_shared_dependents,
    run_aql_event_search,
    check_field_extraction_configured,
    check_field_population_rate,
)
from app.rule_analyzer.llm_provider import LLMProvider
from app.rule_analyzer.rule_chain_context import format_full_chain_inline
from app.services.qradar_client import QRadarClient
from app.rule_analyzer.final_report_schema import FinalReport
from app.rule_analyzer.report_renderer import render_report

_INVESTIGATION_SYSTEM_PROMPT = """You are continuing your analysis of a QRadar rule, now with access to investigation tools.

You've already produced an initial structural analysis, shown below alongside the rule's full chain. Now investigate further using the available tools. Concrete examples of when a tool is clearly worth calling:
  - Checking who else depends on a building block before recommending it be disabled.
  - Checking reference data dependencies if the rule relies on one and no other structural cause is apparent.
  - Checking whether the rule (or a referenced building block) was recently modified if nothing else explains a rule that "used to work."
  - Checking the log source(s) for the log source type the rule requires -- are they all disabled, or all enabled? For any enabled ones, when was the last event received -- if it's been roughly 2 weeks or longer with no event, that log source is very likely not actively sending data, which would explain a rule that never fires.
  - Checking the LIVE contents of a reference set the rule depends on -- is it empty, or do the real stored values look formatted differently than what the rule's condition checks?

IMPORTANT: if your structural analysis found NO obvious flags (an empty structural_flags list), that is NOT a reason to stop -- it means the answer likely lies in LIVE data, not in the rule's own definition. A structurally clean rule with reference set or log source dependencies is EXACTLY the case these tools exist for. Skip a tool only when it's genuinely not applicable to this rule (e.g. no reference set dependency exists at all) -- not because the structural analysis already looked clean.

When you are done investigating (whether you used any tools or not), respond with a final plain-text summary of what you found. Do not call any more tools once you've reached a conclusion."""

# _REPORT_PROMPT = (
#     "Based on the full investigation above, write a clear, structured final report for a "
#     "detection engineer, covering: (1) what this rule is meant to detect, (2) the most likely "
#     "reason(s) it may not be firing/working as expected, ranked by confidence, (3) concrete "
#     "next steps to confirm or fix each likely cause. If nothing structurally looks wrong, say "
#     "so plainly and suggest the next investigation should move to live QRadar data.\n\n"
#     "SEPARATELY, if while investigating you noticed something suspicious or a potential NEW "
#     "detection opportunity that is OUTSIDE the scope of the rule you were asked to investigate "
#     "(e.g. live data revealed a real security-relevant pattern this rule was never designed to "
#     "catch), include it in its own clearly labeled section at the very end, titled "
#     "'ADDITIONAL FINDINGS / POTENTIAL NEW RULE OPPORTUNITY'. For each one, state: what you "
#     "observed, the specific live evidence that supports it, and a concrete suggested next step "
#     "(e.g. propose a new rule, or flag for the team to review). Only include this section if "
#     "you genuinely found something -- do not invent one. This section must never replace or "
#     "distract from your primary analysis above; it is strictly additional."
# )
_REPORT_PROMPT = (
    "Based on the full investigation above, produce a structured final report for a detection "
    "engineer. detection_intent: what this rule is meant to catch, in plain language. "
    "structural_summary: one or two sentences on whether the rule's own structure/config looks "
    "fine. root_causes: every plausible reason ranked by confidence, each with specific evidence "
    "and concrete next steps -- if nothing structurally looks wrong, root_causes should focus on "
    "live-data findings instead. overall_recommendation: the single best next action. "
    "additional_findings: ONLY include something here if you genuinely noticed a suspicious "
    "pattern or new detection opportunity OUTSIDE this rule's scope during your investigation -- "
    "leave it empty otherwise, never invent one."
)


def build_tools(db: Session, customer_id: int, qradar_client: QRadarClient):
    """Closures over db/customer_id/qradar_client -- the LLM only ever
    supplies the decision-relevant argument (the identifier string it
    can actually see in the chain text), never the database session or
    the QRadar client itself, same pattern as build_agent_graph(driver)
    in the Q&A agent."""
    from langchain_core.tools import tool

    @tool
    def find_shared_dependents(bb_identifier: str) -> str:
        """Find which OTHER rules also depend on a given building block identifier. Use this to assess how widely-relied-upon a building block is before concluding it's the root cause of an issue -- a BB used by 40 rules is a very different risk than one used by only this rule."""
        return get_shared_dependents(db, customer_id, bb_identifier)

    @tool
    def check_reference_data(identifier: str) -> str:
        """Check which reference sets/maps a specific rule/building block's OWN conditions depend on. Pass the IDENTIFIER string shown in the rule chain (e.g. "SYSTEM-1300", or the root rule's own identifier) -- NOT an internal ID. Only checks that ONE rule/BB's own conditions, not nested building blocks -- call again with a nested building block's own identifier if it also needs checking. Use this if the chain shows a reference set/map dependency and no other structural cause explains the issue."""
        return check_reference_data_dependencies(db, customer_id, identifier)

    @tool
    def check_timing(identifier: str) -> str:
        """Check when a specific rule/building block was created and last modified. Pass the IDENTIFIER string shown in the rule chain (e.g. "SYSTEM-1300", or the root rule's own identifier) -- NOT an internal ID. A recent modification (hours ago) well after original creation is a strong signal something was just changed. Call this on the root rule's own identifier, or on a specific referenced building block's identifier, if you suspect a recent edit is relevant."""
        return check_rule_timing(db, customer_id, identifier)

    @tool
    def check_log_source(identifier: str) -> str:
        """Check LIVE QRadar data for the log source type a specific rule/building block's own conditions require. Pass the IDENTIFIER string shown in the rule chain (e.g. "SYSTEM-1300", or the root rule's own identifier) -- NOT an internal ID. Use this if the chain shows a required log source type and no other structural cause (disabled rule/BB, missing reference data) explains the issue. This makes a LIVE call to the customer's QRadar console."""
        return check_log_source_status(db, qradar_client, customer_id, identifier)

    @tool
    def check_reference_set_live(identifier: str) -> str:
        """Check the LIVE, real contents of the reference set(s) a specific rule/building block's own conditions depend on. Pass the IDENTIFIER string shown in the rule chain (e.g. "SYSTEM-1300", or the root rule's own identifier) -- NOT an internal ID. Reports whether each set exists, its real entry count (0 entries directly explains a rule that never matches), and a sample of real values -- useful to confirm or rule out a value-format mismatch (e.g. the rule checks a plain username but the set stores "DOMAIN\\username"). Use this after check_reference_data has confirmed a reference set dependency and no other structural cause explains the issue. This makes a LIVE call to the customer's QRadar console."""
        return check_reference_set_contents(db, qradar_client, customer_id, identifier)

    @tool
    def check_field_extraction(identifier: str, field_name: str) -> str:
        """Check whether ANY extraction (regex/JSON/XML/CEF/LEEF/NVP/AQL) is even configured for a custom field, on the log source type this rule/BB requires. Pass the IDENTIFIER string shown in the rule chain and the exact field name the rule's condition checks (e.g. "Policy Action"). Use this FIRST, before check_field_population -- if no extraction is configured at all, that alone explains an always-empty field with no live event data needed."""
        return check_field_extraction_configured(db, qradar_client, customer_id, identifier, field_name)

    @tool
    def check_field_population(field_name: str, qid: int, log_source_type: str) -> str:
        """Check whether a custom field is actually populated on real recent events for a specific QID, or mostly/always NULL/empty -- confirms or rules out a parsing/mapping problem as the reason a rule's field-based condition never matches. Unlike run_aql_search, this builds ITS OWN safe, deterministic query -- just pass the field name (e.g. "Policy Action"), the QID, and the exact log source type. Use this AFTER check_field_extraction has confirmed the field IS configured but you still suspect it's not populating correctly on real events."""
        return check_field_population_rate(qradar_client, field_name, qid, log_source_type)

    aql_search_count = {"count": 0}
    MAX_AQL_SEARCHES = 2

    def _run_aql_search_impl(aql_query: str, log_source_type: str) -> str:
        if aql_search_count["count"] >= MAX_AQL_SEARCHES:
            return (
                f"AQL search budget exhausted for this investigation ({MAX_AQL_SEARCHES} used). "
                "Conclude with the evidence already gathered rather than searching further."
            )
        aql_search_count["count"] += 1
        return run_aql_event_search(qradar_client, aql_query, log_source_type)

    # StructuredTool.from_function, not @tool, deliberately -- the
    # description is BUILT from an imported template module
    # (aql_prompt_templates.py), and LangChain's @tool decorator can
    # only read a function's LITERAL docstring, not an f-string or an
    # imported variable placed there (Python doesn't recognize either
    # as a real __doc__). from_function's explicit description= param
    # sidesteps that entirely.
    from langchain_core.tools import StructuredTool

    run_aql_search = StructuredTool.from_function(
        func=_run_aql_search_impl,
        name="run_aql_search",
        description=AQL_TOOL_DESCRIPTION,
    )

    return [
        find_shared_dependents,
        check_reference_data,
        check_timing,
        check_log_source,
        check_reference_set_live,
        run_aql_search,
        check_field_extraction,
        check_field_population,
    ]


def build_nodes(db: Session, customer_id: int, llm_provider: LLMProvider, qradar_client: QRadarClient) -> dict:
    """Builds and returns the 4 node functions as a dict keyed by node
    name, ready to be registered onto a StateGraph by
    investigation_graph.py. Kept as ONE factory (rather than 4
    standalone functions) because all 4 nodes share the same
    closed-over dependencies (db, tools, llm instances) -- same
    reasoning as build_agent_graph(driver) in the Q&A agent."""
    tools = build_tools(db, customer_id, qradar_client)
    tool_map = {t.name: t for t in tools}
    llm_with_tools = llm_provider.get_reasoning_llm().bind_tools(tools)
    llm_plain = llm_provider.get_reasoning_llm()

    def analyze_chain_node(state: InvestigationState) -> InvestigationState:
        formatted = format_full_chain_inline(db, customer_id, state["rule_id"])
        if formatted is None:
            return {**state, "final_report": "Rule not found."}

        analysis = analyze_rule_chain(llm_provider, formatted)

        context = (
            f"{_INVESTIGATION_SYSTEM_PROMPT}\n\n"
            f"RULE CHAIN:\n{formatted}\n\n"
            f"INITIAL STRUCTURAL ANALYSIS:\n"
            f"Detection intent: {analysis.detection_intent}\n"
            f"Preconditions: {analysis.preconditions}\n"
            f"Structural flags: {analysis.structural_flags}"
        )

        return {
            **state,
            "chain_analysis": analysis,
            "formatted_chain": formatted,
            "messages": [SystemMessage(content=context)],
            "iterations": 0,
        }

    def investigate_node(state: InvestigationState) -> InvestigationState:
        response = llm_with_tools.invoke(state["messages"])
        return {**state, "messages": state["messages"] + [response]}

    def execute_tools_node(state: InvestigationState) -> InvestigationState:
        last_message = state["messages"][-1]
        tool_messages = []
        for tool_call in last_message.tool_calls:
            tool_fn = tool_map.get(tool_call["name"])
            result = tool_fn.invoke(tool_call["args"]) if tool_fn else f"Unknown tool: {tool_call['name']}"
            tool_messages.append(ToolMessage(content=str(result), tool_call_id=tool_call["id"]))
        return {
            **state,
            "messages": state["messages"] + tool_messages,
            "iterations": state.get("iterations", 0) + 1,
        }

    # def synthesize_report_node(state: InvestigationState) -> InvestigationState:
    #     final_response = llm_plain.invoke(state["messages"] + [HumanMessage(content=_REPORT_PROMPT)])
    #     return {**state, "final_report": final_response.content}

    # return {
    #     "analyze_chain": analyze_chain_node,
    #     "investigate": investigate_node,
    #     "execute_tools": execute_tools_node,
    #     "synthesize_report": synthesize_report_node,
    # }

    def synthesize_report_node(state: InvestigationState) -> InvestigationState:
        structured_llm = llm_provider.get_reasoning_llm().with_structured_output(FinalReport)
        report = structured_llm.invoke(state["messages"] + [HumanMessage(content=_REPORT_PROMPT)])
        return {**state, "final_report": report}

    return {
        "analyze_chain": analyze_chain_node,
        "investigate": investigate_node,
        "execute_tools": execute_tools_node,
        "synthesize_report": synthesize_report_node,
    }

 