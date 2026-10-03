"""Response/request schemas for the Sigma generation batch API,
gap-analysis results, and similarity search results."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SigmaGenerationRequest(BaseModel):
    rule_names: list[str] | None = Field(
        default=None,
        description="Specific rule names to generate for. Omit or leave null to generate for ALL canonical rules.",
        examples=[None],
    )


class SigmaGenerationJobCreateResponse(BaseModel):
    id: int
    status: str
    total_rules: int


class SigmaGenerationJobDetail(BaseModel):
    id: int
    customer_id: int
    status: str
    requested_rule_names: list[str] | None = None
    total_rules: int
    processed_rules: int
    failed_rules: int
    failed_rule_details: list[dict] | None = None
    error: str | None = None
    created_at: str
    finished_at: str | None = None


class PeerRuleSuggestion(BaseModel):
    source_customer_name: str
    rule_id: int
    title: str
    description: str | None
    level: str | None
    detection: dict
    tags: list[str]
    mitre_source: str | None = None  # 'confirmed' | 'derived' -- only populated by MitreGapAnalyzer
    mitre_confidence: str | None = None  # only populated when mitre_source == 'derived'
    required_log_source_types: list[str] = []  # the PEER rule's real REQUIRES_LOGSOURCE_TYPE targets
    customer_has_required_log_source: bool = True  # can the RECEIVING customer actually use this? True if unknown (no edges) -- never falsely blocks
    similarity_score: float | None = None  # FINAL, trusted score -- reranked when reranking runs, raw embedding score otherwise
    embedding_score: float | None = None  # the RAW embedding-only score, always populated by similarity search -- lets you compare pre/post-rerank


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


class SimilaritySearchResult(BaseModel):
    """Wraps the real suggestions alongside HOW MANY genuine
    candidates were found but excluded as insufficiently relevant --
    lets the UI be honest about "we looked, found some, but they
    weren't good enough" rather than silently returning fewer results
    with no explanation."""

    results: list[PeerRuleSuggestion]
    excluded_low_relevance: int