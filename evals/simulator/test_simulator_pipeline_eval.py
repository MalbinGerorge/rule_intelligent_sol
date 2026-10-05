"""
Integration test for the Rule Simulator pipeline -- runs 2 REAL
Windows-based attack narratives through the full pipeline (Attack
Interpreter -> MITRE Validator -> Reference Log Retriever) against a
real customer's live QRadar console.

FILL IN before running: replace the placeholder log source names
below with REAL, exact log source names from your own environment --
these are customer-specific and can't be guessed.

Deliberately gives FULL detail (exact log source name + server) in
every narrative, so status should resolve to "ok" on the first pass
-- no interactive clarification loop needed here (that loop is a
separate concern, tested with mocks, not against a real blocking
LLM call in a test).

Run: uv run pytest evals/simulator/test_simulator_pipeline_eval.py -v -s
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.agent.simulator.attack_interpreter import AttackInterpreterAgent
from app.agent.simulator.dsm_property_extractor_trial import DSMPropertyExtractor
from app.agent.simulator.mitre_validator import MitreTechniqueValidator
from app.agent.simulator.orchestrator import SimulatorOrchestrator
from app.agent.simulator.reference_log_retriever import ReferenceLogRetriever
from app.core.logging_config import configure_logging, configure_simulator_logging
from app.db.session import engine
from app.rule_analyzer.llm_provider import LLMProvider
from app.services.qradar_client_factory import build_qradar_client_for_customer

TEST_CUSTOMER_NAME = "cotecna"

# FILL IN: real, exact log source names from your own QRadar console.
WINDOWS_LOG_SOURCE_1 = "[Cotecna] - [Windows] - [Server] - GVADEVSQL01"
WINDOWS_LOG_SOURCE_2 = (
    "[Cotecna] - [Windows] - [Server] - GVADEVSQL01"  # fill in a 2nd real one if you have it
)

EVAL_CASES = [
    {
        "id": "rdp_brute_force",
        "narrative": (
            "An attacker attempted a brute-force RDP login against GVADEVSQL01, "
            "resulting in multiple failed logon attempts followed by one successful "
            f"logon, logged in the {WINDOWS_LOG_SOURCE_1} log source."
        ),
        "expected_technique_id": "T1110",
    },
    {
        "id": "scheduled_task_persistence",
        "narrative": (
            "An attacker created a new scheduled task on GVADEVSQL01 for persistence "
            f"after initial access, logged in the {WINDOWS_LOG_SOURCE_2} log source."
        ),
        "expected_technique_id": "T1053",
    },
]


@pytest.fixture(scope="session", autouse=True)
def _configure_test_logging():
    configure_logging(log_level="INFO")
    configure_simulator_logging(log_level="INFO")


@pytest.fixture(scope="module")
def db():
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="module")
def orchestrator(db):
    customer_id = db.execute(
        text("SELECT id FROM customers WHERE name = :name"), {"name": TEST_CUSTOMER_NAME}
    ).scalar_one_or_none()
    if customer_id is None:
        pytest.skip(f"Test customer '{TEST_CUSTOMER_NAME}' not found -- adjust TEST_CUSTOMER_NAME")

    qradar_client = build_qradar_client_for_customer(db, customer_id)
    llm = LLMProvider().get_reasoning_llm()

    return SimulatorOrchestrator(
        interpreter=AttackInterpreterAgent(llm),
        validator=MitreTechniqueValidator(db),
        retriever=ReferenceLogRetriever(qradar_client),
        extractor=DSMPropertyExtractor(db, customer_id),
    )


@pytest.mark.parametrize("case", EVAL_CASES, ids=[c["id"] for c in EVAL_CASES])
def test_windows_attack_scenario(orchestrator, case):
    result = orchestrator.run(case["narrative"])

    print(f"\nStatus: {result.status}")
    print(f"Reasoning: {result.reasoning}")

    assert result.status == "ok", (
        f"Expected 'ok' (full detail was given) but got 'needs_clarification': "
        f"{result.clarification_question}"
    )
    assert len(result.step_results) >= 1

    step = result.step_results[0].step
    print(f"MITRE: confirmed={step.mitre_confirmed}, id={step.confirmed_technique_id}")
    assert step.mitre_confirmed is True
    assert step.confirmed_technique_id == case["expected_technique_id"]

    extracted = result.step_results[0].extracted_properties
    assert extracted, "Real events came back but no properties were extracted"
    assert any("EventID" in e.as_dict() for e in extracted), (
        "No EventID extracted from any reference event -- check that the payload "
        "is WinCollect-style key=value text and that the retriever's AQL alias is 'Payload'"
    )

    reference = result.step_results[0].reference_sample
    print(f"Reference: source={reference.source if reference else None}")
    assert reference is not None
    if reference.source != "qradar":
        pytest.fail(
            f"Expected a real reference sample but got source={reference.source!r} -- "
            f"check that WINDOWS_LOG_SOURCE constants above are exact, real names."
        )
