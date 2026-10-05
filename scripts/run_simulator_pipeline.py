"""
Runs the full Rule Simulator pipeline (Attack Interpreter -> MITRE
Validator -> Reference Log Retriever) against ONE real customer's
live QRadar console.



Usage:
    uv run python scripts/run_simulator_pipeline.py --customer cotecna "Mimikatz credential dump on DC01, caught by Sysmon"
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.agent.simulator.attack_interpreter import AttackInterpreterAgent
from app.agent.simulator.dsm_property_extractor_trial import DSMPropertyExtractor
from app.agent.simulator.interactive_runner import run_interactive
from app.agent.simulator.mitre_validator import MitreTechniqueValidator
from app.agent.simulator.orchestrator import SimulatorOrchestrator
from app.agent.simulator.reference_log_retriever import ReferenceLogRetriever
from app.ai.llm.provider import LLMProvider
from app.core.logging import configure_logging, configure_simulator_logging
from app.db.session import engine
from app.integrations.qradar.client_factory import build_qradar_client_for_customer


def _short(value: str, limit: int = 80) -> str:
    return value if len(value) <= limit else value[:limit] + "…"


def print_extracted(extracted_properties) -> None:
    for index, extracted in enumerate(extracted_properties, start=1):
        regex_count = sum(1 for p in extracted.properties if p.method == "regex")
        print(
            f"    Extracted properties, event {index}: {len(extracted.properties)} total, "
            f"{regex_count} via QRadar expressions"
        )
        for prop in extracted.properties:
            print(f"      {prop.name} = {_short(prop.value)!r}  ({prop.method})")
        if extracted.skipped_expression_counts:
            print(f"      skipped expressions: {extracted.skipped_expression_counts}")
        print(f"      raw_message: {_short(extracted.raw_message, 120)!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--customer", required=True, help="customer name, e.g. cotecna")
    parser.add_argument("narrative", help="the attack narrative to simulate")
    args = parser.parse_args()

    configure_logging(log_level="INFO")
    configure_simulator_logging(log_level="INFO")

    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        customer_id = db.execute(
            text("SELECT id FROM customers WHERE name = :name"), {"name": args.customer}
        ).scalar_one_or_none()

        if not customer_id:
            raise SystemExit(f"Customer '{args.customer}' not found.")

        qradar_client = build_qradar_client_for_customer(db, customer_id)
        llm = LLMProvider().get_reasoning_llm()

        orchestrator = SimulatorOrchestrator(
            interpreter=AttackInterpreterAgent(llm),
            validator=MitreTechniqueValidator(db),
            retriever=ReferenceLogRetriever(qradar_client),
            extractor=DSMPropertyExtractor(db, customer_id),
        )

        result = run_interactive(orchestrator.interpreter, orchestrator, args.narrative)

        print(f"\nStatus: {result.status}")
        print(f"Reasoning: {result.reasoning}")
        if result.clarification_question:
            print(f"Clarification needed: {result.clarification_question}")

        for sr in result.step_results:
            step = sr.step
            print(f"\n  Step {step.step_number}: {step.technique_name}")
            print(
                f"    MITRE: confirmed={step.mitre_confirmed}, id={step.confirmed_technique_id}, "
                f"name={step.confirmed_technique_name}"
            )
            print(f"    Target: {step.target_server} / {step.target_log_source}")
            if sr.reference_sample:
                print(
                    f"    Reference: source={sr.reference_sample.source}, "
                    f"log_source={sr.reference_sample.log_source_name}"
                )
                print_extracted(sr.extracted_properties)

                if sr.reference_sample.available_alternatives:
                    print(f"    Did you mean one of: {sr.reference_sample.available_alternatives}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
