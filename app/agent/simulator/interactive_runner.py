"""
Interactive clarification loop -- runs the Attack Interpreter
repeatedly, asking the analyst directly whenever it needs more
detail, until it has enough to proceed (or a round limit is hit).

Deliberately loops ONLY the interpreter (cheap, no QRadar/DB cost) --
MITRE validation and reference log retrieval run exactly ONCE, after
clarification is resolved, via SimulatorOrchestrator.process_steps().
Looping the FULL pipeline per round would waste real resources on
steps that were already fine while waiting on an unrelated one.

ask_user is injectable -- defaults to the real terminal input(), but
can be swapped for a test stub, or later, a web UI's own question/
answer mechanism (this loop's logic doesn't care which).
"""
from __future__ import annotations

from typing import Callable

import structlog

from app.agent.simulator.attack_interpreter import AttackInterpreterAgent
from app.agent.simulator.orchestrator import SimulatorOrchestrator
from app.agent.simulator.schemas import PipelineResult

logger = structlog.get_logger(__name__)

MAX_CLARIFICATION_ROUNDS = 3


def run_interactive(
    interpreter: AttackInterpreterAgent,
    orchestrator: SimulatorOrchestrator,
    initial_narrative: str,
    ask_user: Callable[[str], str] = input,
) -> PipelineResult:
    context = initial_narrative

    for round_num in range(1, MAX_CLARIFICATION_ROUNDS + 1):
        interpreted = interpreter.interpret(context)

        if interpreted.status == "ok":
            step_results = orchestrator.process_steps(interpreted.steps)
            logger.info("clarification_resolved", rounds_needed=round_num - 1)
            return PipelineResult(
                status="ok",
                reasoning=interpreted.reasoning,
                step_results=step_results,
            )

        logger.info(
            "clarification_round",
            round=round_num,
            question=interpreted.clarification_question,
        )
        answer = ask_user(f"\n{interpreted.clarification_question}\n> ")

        context = (
            f"{context}\n\n"
            f"Clarification asked: {interpreted.clarification_question}\n"
            f"Analyst's answer: {answer}"
        )

    # Ran out of rounds -- return the last known state honestly,
    # rather than looping forever or silently guessing at this point.
    logger.warning("clarification_rounds_exhausted", max_rounds=MAX_CLARIFICATION_ROUNDS)
    return PipelineResult(
        status="needs_clarification",
        reasoning=interpreted.reasoning,
        clarification_question=(
            f"Still unclear after {MAX_CLARIFICATION_ROUNDS} rounds: {interpreted.clarification_question}"
        ),
        step_results=[],
    )