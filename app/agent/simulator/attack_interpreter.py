"""
Attack Interpreter Agent -- turns an analyst's free-text narrative
into structured attack steps.

RBAC: this agent's role (see app/agents/rbac/roles.py) has an EMPTY
tool allow-list, deliberately -- pure text-in, structured-json-out
reasoning, no external calls at all. No rbac_enforced() wrapper is
needed here for that reason; the empty role itself is the guarantee.
"""

from __future__ import annotations

import time

import structlog

from app.agent.simulator.prompts import build_interpreter_messages
from app.agent.simulator.schemas import AttackInterpreterOutput

logger = structlog.get_logger(__name__)


class AttackInterpreterAgent:
    def __init__(self, llm):
        self._structured_llm = llm.with_structured_output(AttackInterpreterOutput)

    def interpret(self, narrative: str) -> AttackInterpreterOutput:
        started_at = time.perf_counter()
        messages = build_interpreter_messages(narrative)
        result = self._structured_llm.invoke(messages)
        duration_ms = round((time.perf_counter() - started_at) * 1000, 1)

        logger.info(
            "attack_interpreter_completed",
            narrative=narrative,
            status=result.status,
            step_count=len(result.steps),
            reasoning=result.reasoning,
            duration_ms=duration_ms,
        )
        return result
