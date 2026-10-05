"""
Manual test: run the Attack Interpreter agent against real narratives,
using the REAL Azure OpenAI reasoning deployment -- a wrong "ok" here
risks a wasted or wrong query against a live QRadar console, so this
uses the same higher-stakes tier as the Q&A agent / investigation
loop, not the fast/cheap one.

Usage:
    uv run python scripts/test_attack_interpreter.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.simulator.attack_interpreter import AttackInterpreterAgent
from app.ai.llm.provider import LLMProvider
from app.core.logging import configure_logging, configure_simulator_logging

configure_logging(log_level="INFO")
configure_simulator_logging(log_level="INFO")

TEST_NARRATIVES = [
    "Mimikatz credential dump on DC01, caught by Sysmon",
    "We ran mimikatz to dump credentials",  # missing everything
    # Multi-step: tests whether it correctly numbers/splits steps
    "Mimikatz credential dump on DC01 via Sysmon, then PsExec lateral move to FILESRV01 using Windows Security Event Log",
    # Partial: one step complete, one step missing detail -- tests
    # whether it correctly flags ONLY the incomplete step
    "Credential dump on DC01 caught by Sysmon, followed by lateral movement to another server",
    # Log source given, server missing -- the inverse of what we tested
    "PsExec lateral movement caught in Sysmon logs",
    # No attack-relevant content at all -- tests it doesn't hallucinate a technique
    "The weather was nice yesterday and I had lunch with the team",
    # A vague technique name with NO tool/server/source, but real
    # MITRE-adjacent language -- tests it doesn't over-guess a technique_id
    "Someone tried privilege escalation somewhere in the network",
]


def main() -> None:
    provider = LLMProvider()
    agent = AttackInterpreterAgent(provider.get_reasoning_llm())

    for narrative in TEST_NARRATIVES:
        print(f"\n{'=' * 60}\nNarrative: {narrative}\n{'=' * 60}")
        result = agent.interpret(narrative)
        print(f"Status: {result.status}")
        print(f"Reasoning: {result.reasoning}")
        if result.clarification_question:
            print(f"Clarification needed: {result.clarification_question}")
        for step in result.steps:
            print(
                f"  Step {step.step_number}: {step.technique_name} "
                f"(log_source={step.target_log_source}, server={step.target_server}, "
                f"ready={step.has_enough_detail})"
            )


if __name__ == "__main__":
    main()
