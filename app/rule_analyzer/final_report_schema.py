"""
Structured final report schema -- CONFIRMED NECESSARY from real,
repeated observation across multiple live runs of this same rule: free
text produces genuinely different formatting every time (numbered
lists vs markdown headers, different section orderings), even though
the underlying reasoning was consistently good. Same fix already
proven for ChainAnalysis: force a Pydantic shape via
with_structured_output(), THEN a Jinja template renders that
guaranteed shape identically every time, regardless of how the model
phrased anything internally.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RootCause(BaseModel):
    cause: str = Field(description="A specific, concrete reason this rule may not be firing/working as expected")
    confidence: Literal["high", "medium", "low"] = Field(description="Confidence this is the actual root cause")
    evidence: list[str] = Field(description="Specific live/structural evidence supporting this, as separate bullet points")
    next_steps: list[str] = Field(description="Concrete actions to confirm or fix this specific cause")


class NewRuleOpportunity(BaseModel):
    observation: str = Field(description="What was noticed, outside the scope of the rule under investigation")
    evidence: list[str] = Field(description="The specific live data supporting this observation")
    suggested_next_step: str = Field(description="A concrete suggestion, e.g. propose a new rule, or flag for team review")


class FinalReport(BaseModel):
    detection_intent: str = Field(description="What this rule is meant to detect, in plain language")
    structural_summary: str = Field(description="A brief statement on whether the rule's own structure/configuration looks fine")
    root_causes: list[RootCause] = Field(description="Every plausible reason found, ranked from most to least confident")
    overall_recommendation: str = Field(description="A short, direct summary of the single best next action")
    additional_findings: list[NewRuleOpportunity] = Field(
        default_factory=list,
        description=(
            "Anything suspicious or a potential NEW detection opportunity noticed OUTSIDE the scope "
            "of the rule under investigation. Leave EMPTY if nothing genuine was found -- never invent one."
        ),
    )