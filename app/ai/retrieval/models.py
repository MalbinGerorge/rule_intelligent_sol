"""Result types produced by similarity search (and reused by gap analysis)."""

from __future__ import annotations

from pydantic import BaseModel


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
    required_log_source_types: list[
        str
    ] = []  # the PEER rule's real REQUIRES_LOGSOURCE_TYPE targets
    customer_has_required_log_source: bool = True  # can the RECEIVING customer actually use this? True if unknown (no edges) -- never falsely blocks
    similarity_score: float | None = (
        None  # FINAL, trusted score -- reranked when reranking runs, raw embedding score otherwise
    )
    embedding_score: float | None = (
        None  # the RAW embedding-only score, always populated by similarity search -- lets you compare pre/post-rerank
    )


class SimilaritySearchResult(BaseModel):
    """Wraps the real suggestions alongside HOW MANY genuine
    candidates were found but excluded as insufficiently relevant --
    lets the UI be honest about "we looked, found some, but they
    weren't good enough" rather than silently returning fewer results
    with no explanation."""

    results: list[PeerRuleSuggestion]
    excluded_low_relevance: int
