"""
Pydantic schemas for the Rule Simulator's agent pipeline. Kept in one
file, separate from prompts and invocation logic, since several
schemas here will be shared/referenced across multiple pipeline steps
as later agents (Field Substitution, Verifier) are built.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class AttackStep(BaseModel):
    step_number: int
    technique_id: str | None = Field(None, description="MITRE ATT&CK ID, if identifiable, e.g. 'T1003'")
    technique_name: str = Field(description="Short name, e.g. 'Credential dumping via Mimikatz'")
    target_log_source: str | None = Field(
        None, description="Explicitly stated log source, e.g. 'Windows Security Event Log', 'Sysmon'"
    )
    target_server: str | None = Field(None, description="Explicitly stated target server, e.g. 'DC01'")

    # Filled in by MitreTechniqueValidator, AFTER the interpreter --
    # NOT trusted from the LLM's own guess. None until validated.
    mitre_confirmed: bool | None = None
    confirmed_technique_id: str | None = None
    confirmed_technique_name: str | None = None

    @property
    def has_enough_detail(self) -> bool:
        """Only the log source is REQUIRED -- target_server may
        legitimately be null for tenant-wide sources (Azure AD, M365,
        other cloud/SaaS logs with no per-host concept). Whether a
        server was genuinely needed is the interpreter's own judgment
        call (see prompts.py), not re-derived here with a rigid rule."""
        return self.target_log_source is not None


class ReferenceLogSample(BaseModel):
    """A real, confirmed sample event to use as a template -- NEVER
    invented from general knowledge. source is 'qradar' when a real
    match was found on the target console; 'not_found' means no
    matching log source or no recent events exist for it (a genuine,
    honest outcome -- not an error)."""

    source: str = Field(description="'qradar' or 'not_found'")
    log_source_name: str | None = None
    log_source_id: int | None = None
    log_source_type_id: int | None = Field(
        None,
        description="QRadar's type id for this log source (e.g. 12 = Windows Security) -- "
        "needed to pick which DSM extraction expressions apply to its events",
    )
    raw_events: list[dict] = Field(
        default_factory=list,
        description="Up to REFERENCE_SAMPLE_LIMIT real sample events -- a small handful "
        "for cross-checking, never a bulk pull",
    )
    available_alternatives: list[str] = Field(
        default_factory=list,
        description="Real, configured log source names that PARTIALLY matched "
        "(server or type, not both) -- only populated when source='not_found', "
        "so the analyst can correct their narrative with real options.",
    )


class ExtractedProperty(BaseModel):
    name: str
    value: str
    method: str = Field(description="'nvp_generic' (built-in key=value pass) or 'regex' (a synced QRadar expression)")


class ExtractedProperties(BaseModel):
    """Result of running one raw payload through QRadar's OWN synced
    extraction expressions only -- these are what a real rule could
    actually reference. raw_message is kept separately, unparsed, as
    fallback context for whatever no synced expression captured --
    never split into properties itself. Skipped counts show gaps in
    extraction coverage (e.g. unsupported expression types), never
    silent."""

    properties: list[ExtractedProperty] = []
    raw_message: str = ""
    skipped_expression_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Applicable expressions NOT applied, keyed by reason/type "
        "(e.g. 'json', 'cef', 'invalid_regex') -- shows what extraction didn't cover",
    )

    def as_dict(self) -> dict[str, str]:
        return {p.name: p.value for p in self.properties}

    
class StepResult(BaseModel):
    """One attack step, carried through MITRE validation, (if ready)
    reference log retrieval, and DSM property extraction -- the full
    per-step outcome. extracted_properties has one entry per
    reference event THAT HAD A PAYLOAD, in raw_events order (an event
    without one is skipped with a warning, so lengths can differ)."""

    step: AttackStep
    reference_sample: ReferenceLogSample | None = None
    extracted_properties: list[ExtractedProperties] = []


class PipelineResult(BaseModel):
    """The orchestrator's full output for one narrative -- mirrors
    AttackInterpreterOutput's status/reasoning, but with each step
    now carrying its validated MITRE mapping and reference sample."""

    status: str
    reasoning: str
    clarification_question: str | None = None
    step_results: list[StepResult] = []


class AttackInterpreterOutput(BaseModel):
    status: str = Field(description="'ok' or 'needs_clarification'")
    reasoning: str = Field(
        description="Brief explanation of how the narrative was interpreted -- "
        "why these steps/techniques were identified, and why status was chosen"
    )
    clarification_question: str | None = None
    steps: list[AttackStep] = []