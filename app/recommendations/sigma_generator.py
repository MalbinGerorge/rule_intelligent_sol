"""
ONE class, ONE public method: SigmaGenerator.generate_and_save().
Internally decides simple vs. correlation and routes accordingly --
callers never need to know or check which path a given rule takes.
"""
from __future__ import annotations

import json
import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.recommendations.sigma_prompts import build_correlation_generation_prompt, build_sigma_generation_prompt
from app.recommendations.sigma_schema import SigmaCorrelationGeneration, SigmaDetection, SigmaRuleGeneration
from app.rule_analyzer.llm_provider import LLMProvider
from app.rule_analyzer.rule_chain_context import format_full_chain_inline

THRESHOLD_TEST_CLASSES = {
    "ThresholdFunction_Test",
    "TriggerMatchCount",
    "MatchCount",
    "SequenceFunction_Test",
    "DoubleSequenceFunction_Test",
    "CauseAndEffect_Test",
    "TriggerTimeout",
}


def _detection_to_sigma_dict(detection: SigmaDetection) -> dict:
    """Converts the LLM-safe list-based SigmaDetection into real
    Sigma-shaped dict format -- {selection_name: {field[|modifier]: value}}."""
    selections = {}
    for sel in detection.selections:
        field_dict = {}
        for fv in sel.field_values:
            key = f"{fv.field}|{fv.modifier}" if fv.modifier else fv.field
            field_dict[key] = fv.values if len(fv.values) > 1 else fv.values[0]
        selections[sel.name] = field_dict
    return {"selections": selections, "condition": detection.condition}


class SigmaGenerator:
    def __init__(self, llm_provider: LLMProvider):
        self.llm_provider = llm_provider

    def requires_correlation(self, db: Session, rule_id: int) -> bool:
        count = db.execute(
            text("SELECT count(*) FROM rule_conditions WHERE rule_id = :rule_id AND test_class = ANY(:classes)"),
            {"rule_id": rule_id, "classes": list(THRESHOLD_TEST_CLASSES)},
        ).scalar_one()
        return count > 0

    def _rule_mitre(self, db: Session, rule_id: int) -> tuple[list[str], list[str], list[str]]:
        row = db.execute(
            text("SELECT tactics, techniques, sub_techniques FROM rule_summary WHERE id = :rule_id"),
            {"rule_id": rule_id},
        ).mappings().first()
        return (
            (row["tactics"] if row else []) or [],
            (row["techniques"] if row else []) or [],
            (row["sub_techniques"] if row else []) or [],
        )

    def generate_and_save(self, db: Session, customer_id: int, rule_id: int) -> dict:
        """The ONE entry point. Returns {"role": "standalone"|"correlation",
        "ids": [id] or [base_id, correlation_id], "generation": <the raw
        Pydantic object, for trace/inspection purposes>}."""
        chain_text = format_full_chain_inline(db, customer_id, rule_id)
        if chain_text is None:
            raise ValueError(f"Rule {rule_id} not found for customer {customer_id}")

        tactics, techniques, sub_techniques = self._rule_mitre(db, rule_id)

        if self.requires_correlation(db, rule_id):
            prompt = build_correlation_generation_prompt(tactics, techniques, sub_techniques)
            structured_llm = self.llm_provider.get_reasoning_llm().with_structured_output(SigmaCorrelationGeneration)
            generation = structured_llm.invoke(
                [SystemMessage(content=prompt), HumanMessage(content=f"RULE CHAIN:\n{chain_text}")]
            )
            base_id, correlation_id = self._save_correlation(db, customer_id, rule_id, generation)
            return {"role": "correlation", "ids": [base_id, correlation_id], "generation": generation}

        prompt = build_sigma_generation_prompt(tactics, techniques, sub_techniques)
        structured_llm = self.llm_provider.get_reasoning_llm().with_structured_output(SigmaRuleGeneration)
        generation = structured_llm.invoke(
            [SystemMessage(content=prompt), HumanMessage(content=f"RULE CHAIN:\n{chain_text}")]
        )
        new_id = self._save_standalone(db, customer_id, rule_id, generation)
        return {"role": "standalone", "ids": [new_id], "generation": generation}

    def _save_standalone(self, db: Session, customer_id: int, rule_id: int, generation: SigmaRuleGeneration) -> int:
        sigma_id = str(uuid.uuid4())
        row = db.execute(
            text(
                """
                INSERT INTO rule_yaml_representations
                    (rule_id, customer_id, sigma_id, title, description, status, level,
                     logsource, detection, tags, falsepositives, "references", mitre_techniques_inferred)
                VALUES
                    (:rule_id, :customer_id, :sigma_id, :title, :description, :status, :level,
                     :logsource, :detection, :tags, :falsepositives, :references, :mitre_techniques_inferred)
                RETURNING id
                """
            ),
            {
                "rule_id": rule_id,
                "customer_id": customer_id,
                "sigma_id": sigma_id,
                "title": generation.title,
                "description": generation.description,
                "status": generation.status,
                "level": generation.level,
                "logsource": generation.logsource.model_dump_json(),
                "detection": json.dumps(_detection_to_sigma_dict(generation.detection)),
                "tags": json.dumps(generation.tags),
                "falsepositives": json.dumps(generation.falsepositives),
                "references": json.dumps([]),
                "mitre_techniques_inferred": json.dumps(
                    [t.model_dump() for t in generation.mitre_techniques_inferred]
                ),
            },
        )
        return row.scalar_one()

    def _save_correlation(
        self, db: Session, customer_id: int, rule_id: int, generation: SigmaCorrelationGeneration
    ) -> tuple[int, int]:
        base_sigma_id = str(uuid.uuid4())
        base_row = db.execute(
            text(
                """
                INSERT INTO rule_yaml_representations
                    (rule_id, customer_id, sigma_id, title, description, status, level,
                     logsource, detection, tags, "references", mitre_techniques_inferred,
                     role, rule_reference_name)
                VALUES
                    (:rule_id, :customer_id, :sigma_id, :title, :description, :status, :level,
                     :logsource, :detection, :tags, :references, :mitre_techniques_inferred,
                     'base', :reference_name)
                RETURNING id
                """
            ),
            {
                "rule_id": rule_id,
                "customer_id": customer_id,
                "sigma_id": base_sigma_id,
                "title": generation.base_title,
                "description": generation.base_description,
                "status": generation.base_status,
                "level": generation.base_level,
                "logsource": generation.base_logsource.model_dump_json(),
                "detection": json.dumps(_detection_to_sigma_dict(generation.base_detection)),
                "tags": json.dumps(generation.base_tags),
                "references": json.dumps([]),
                "mitre_techniques_inferred": json.dumps([]),
                "reference_name": generation.reference_name,
            },
        )
        base_id = base_row.scalar_one()

        correlation_sigma_id = str(uuid.uuid4())
        correlation_row = db.execute(
            text(
                """
                INSERT INTO rule_yaml_representations
                    (rule_id, customer_id, sigma_id, title, description, status, level,
                     detection, tags, falsepositives, "references", mitre_techniques_inferred,
                     role, correlation)
                VALUES
                    (:rule_id, :customer_id, :sigma_id, :title, :description, :status, :level,
                     :detection, :tags, :falsepositives, :references, :mitre_techniques_inferred,
                     'correlation', :correlation)
                RETURNING id
                """
            ),
            {
                "rule_id": rule_id,
                "customer_id": customer_id,
                "sigma_id": correlation_sigma_id,
                "title": generation.correlation_title,
                "description": generation.correlation_description,
                "status": generation.correlation_status,
                "level": generation.correlation_level,
                "detection": json.dumps({}),
                "tags": json.dumps(generation.correlation_tags),
                "falsepositives": json.dumps(generation.correlation_falsepositives),
                "references": json.dumps([]),
                "mitre_techniques_inferred": json.dumps(
                    [t.model_dump() for t in generation.mitre_techniques_inferred]
                ),
                "correlation": generation.correlation.model_dump_json(),
            },
        )
        correlation_id = correlation_row.scalar_one()

        return base_id, correlation_id