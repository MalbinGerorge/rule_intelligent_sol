"""
Rule Simulator pipeline orchestrator -- wires Attack Interpreter ->
MITRE Technique Validator -> Reference Log Retriever -> DSM Property
Extractor.

process_steps() is exposed SEPARATELY from run() so an interactive
clarification loop (see interactive_runner.py) can call it ONCE,
after the analyst has supplied enough detail -- re-running the full
pipeline on every clarification round would waste real MITRE catalog
+ QRadar queries on steps that were already fine.
"""

from __future__ import annotations

import time

import structlog

from app.agent.simulator.attack_interpreter import AttackInterpreterAgent
from app.agent.simulator.dsm_property_extractor_trial import DSMPropertyExtractor
from app.agent.simulator.mitre_validator import MitreTechniqueValidator
from app.agent.simulator.reference_log_retriever import ReferenceLogRetriever
from app.agent.simulator.schemas import AttackStep, PipelineResult, StepResult

logger = structlog.get_logger(__name__)


class SimulatorOrchestrator:
    def __init__(
        self,
        interpreter: AttackInterpreterAgent,
        validator: MitreTechniqueValidator,
        retriever: ReferenceLogRetriever,
        extractor: DSMPropertyExtractor,
    ):
        self.interpreter = interpreter
        self.validator = validator
        self.retriever = retriever
        self.extractor = extractor

    def run(self, narrative: str) -> PipelineResult:
        """Single-pass: interpret + process, in one call. Use this
        when the narrative is ALREADY known to be complete (e.g. in
        tests, or after an interactive loop has already resolved
        clarification)."""
        started_at = time.perf_counter()
        logger.info("pipeline_run_started", narrative=narrative)

        interpreted = self.interpreter.interpret(narrative)
        step_results = self.process_steps(interpreted.steps)

        duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
        ready_count = sum(1 for sr in step_results if sr.step.has_enough_detail)
        found_count = sum(
            1
            for sr in step_results
            if sr.reference_sample and sr.reference_sample.source == "qradar"
        )
        logger.info(
            "pipeline_run_completed",
            narrative=narrative,
            status=interpreted.status,
            total_steps=len(step_results),
            ready_steps=ready_count,
            reference_samples_found=found_count,
            duration_ms=duration_ms,
        )

        return PipelineResult(
            status=interpreted.status,
            reasoning=interpreted.reasoning,
            clarification_question=interpreted.clarification_question,
            step_results=step_results,
        )

    def process_steps(self, steps: list[AttackStep]) -> list[StepResult]:
        """Runs MITRE validation, reference retrieval and DSM property
        extraction for an ALREADY interpreted list of steps. Exposed
        publicly so callers (like the interactive clarification loop)
        can run this exactly ONCE, on the final steps, rather than
        paying this cost on every round of back-and-forth with the
        analyst."""
        step_results: list[StepResult] = []
        for step in steps:
            validated_step = self.validator.validate(step)

            reference_sample = None
            extracted_properties = []
            if validated_step.has_enough_detail:
                reference_sample = self.retriever.retrieve(validated_step)
                # Only worth extracting when real events actually came back.
                if reference_sample.source == "qradar":
                    extracted_properties = self.extractor.extract_from_sample(reference_sample)

            step_results.append(
                StepResult(
                    step=validated_step,
                    reference_sample=reference_sample,
                    extracted_properties=extracted_properties,
                )
            )
        return step_results
