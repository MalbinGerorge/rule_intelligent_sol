"""Result types produced by gap analysis."""

from __future__ import annotations

from pydantic import BaseModel

from app.ai.retrieval.models import PeerRuleSuggestion


class LogSourceGap(BaseModel):
    log_source_type_name: str
    qradar_type_id: int
    peer_customer_names: list[str]
    suggested_rules: list[PeerRuleSuggestion]


class MitreGap(BaseModel):
    technique_id: str
    technique_name: str | None
    tactic_names: list[str]
    is_subtechnique: bool
    peer_customer_names: list[str]
    suggested_rules: list[PeerRuleSuggestion]
