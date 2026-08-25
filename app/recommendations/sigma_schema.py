"""
ALL structured-output data shapes for Sigma generation, both simple
and threshold/correlation rules, in one file -- genuinely just data
definitions (Pydantic models), no logic, so co-locating them is safe
and easier to navigate than splitting by rule type.

Two SEPARATE top-level schemas (SigmaRuleGeneration vs
SigmaCorrelationGeneration) are still required, not merged into one --
this is a real constraint, not extra complexity for its own sake:
OpenAI's structured-output mode needs ONE fixed schema per LLM call,
and correlation rules need a genuinely different, larger set of
fields (base_* + correlation section) that would make every SIMPLE
rule's call carry a bunch of irrelevant, always-empty fields if merged.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# -- Shared building blocks, used by BOTH schemas below --------------

class SigmaLogsource(BaseModel):
    category: str | None = Field(None, description="e.g. 'process_creation', 'firewall', 'authentication'")
    product: str | None = Field(None, description="e.g. 'windows', 'linux', 'fortigate'")
    service: str | None = Field(None, description="e.g. 'security', 'sysmon' -- optional, more specific than product")


class SigmaFieldValue(BaseModel):
    field: str = Field(description="The field name being checked, e.g. 'EventID', 'QueryName'")
    modifier: str | None = Field(
        None,
        description="How the value should match, if not exact equality: 'contains', 'startswith', 'endswith', or 're' (regex). Leave null for exact match.",
    )
    values: list[str] = Field(description="The value(s) being matched -- a list even for a single value")


class SigmaSelection(BaseModel):
    """A single named selection block. Uses a LIST of fixed-shape
    objects (SigmaFieldValue), not a dict with arbitrary field names
    -- CONFIRMED NECESSARY: OpenAI's strict structured-output mode
    rejects dynamically-keyed dicts."""
    name: str = Field(description="Selection block name, e.g. 'selection', 'filter'")
    field_values: list[SigmaFieldValue]


class SigmaDetection(BaseModel):
    selections: list[SigmaSelection] = Field(
        description="Named selection blocks. Sensitive values must be DE-IDENTIFIED -- described generally, never copied verbatim."
    )
    condition: str = Field(description="e.g. 'selection' or 'selection and not filter'")


class InferredMitreTechnique(BaseModel):
    tactic: str | None = Field(None, description="e.g. 'Credential Access'")
    technique_id: str = Field(description="e.g. 'T1110', or 'T1110.001' for a specific sub-technique")
    technique_name: str
    confidence: Literal["high", "medium", "low"]


# -- Schema 1: SIMPLE rules (one document, no counting/threshold) ----

class SigmaRuleGeneration(BaseModel):
    """Output shape for a rule with NO counting/threshold logic --
    one event either matches or it doesn't."""
    title: str = Field(description="Brief title of what the rule detects, max 256 chars")
    description: str
    status: Literal["stable", "test", "experimental", "deprecated", "unsupported"] = "experimental"
    level: Literal["informational", "low", "medium", "high", "critical"]
    logsource: SigmaLogsource
    detection: SigmaDetection
    tags: list[str] = Field(default_factory=list, description="MITRE tags in 'attack.txxxx' lowercase format")
    falsepositives: list[str] = Field(default_factory=list)
    mitre_techniques_inferred: list[InferredMitreTechnique] = Field(
        default_factory=list,
        description="ONLY populate if the rule had NO existing confirmed MITRE mapping. Leave EMPTY if confirmed mapping was provided.",
    )


# -- Schema 2: CORRELATION rules (base + correlation, two documents) -

class SigmaCorrelationCondition(BaseModel):
    operator: Literal["gt", "gte", "lt", "lte", "eq", "neq"]
    count: int
    field: str | None = Field(None, description="Required for value_count/value_sum/value_avg/value_median/value_percentile types; leave null otherwise.")


class SigmaCorrelation(BaseModel):
    type: Literal[
        "event_count", "value_count", "temporal", "temporal_ordered",
        "value_sum", "value_avg", "value_median", "value_percentile",
    ]
    rules: list[str] = Field(description="Reference name(s) of the base rule(s), matching each base rule's own reference_name exactly.")
    group_by: list[str] = Field(default_factory=list, description="Fields to group events by, e.g. ['Username'].")
    timespan: str = Field(description="Integer + single-char unit: s/m/h/d/w/M(months)/y. E.g. '5m'.")
    condition: SigmaCorrelationCondition


class SigmaCorrelationGeneration(BaseModel):
    """Output shape for a rule involving counting/thresholding
    occurrences over time -- requires TWO linked Sigma documents
    (CONFIRMED from the real Sigma spec), captured here as one
    structured-output call with base_*/correlation_* prefixed fields."""
    base_title: str = Field(description="Title for the BASE detection rule -- the event pattern being counted, WITHOUT threshold logic.")
    base_description: str
    base_status: Literal["stable", "test", "experimental", "deprecated", "unsupported"] = "experimental"
    base_level: Literal["informational", "low", "medium", "high", "critical"]
    base_logsource: SigmaLogsource
    base_detection: SigmaDetection
    base_tags: list[str] = Field(default_factory=list)
    reference_name: str = Field(description="Short, unique, filename-safe reference name for the base rule (lowercase, underscores, no spaces).")

    correlation_title: str = Field(description="Title for the CORRELATION rule -- the full 'multiple X in Y time' detection.")
    correlation_description: str
    correlation_status: Literal["stable", "test", "experimental", "deprecated", "unsupported"] = "experimental"
    correlation_level: Literal["informational", "low", "medium", "high", "critical"]
    correlation: SigmaCorrelation
    correlation_tags: list[str] = Field(default_factory=list)
    correlation_falsepositives: list[str] = Field(default_factory=list)

    mitre_techniques_inferred: list[InferredMitreTechnique] = Field(default_factory=list)