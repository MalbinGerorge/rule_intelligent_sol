"""
Cross-encoder reranking for similarity search results -- re-scores
each (query, candidate) pair TOGETHER, unlike embedding-based cosine
similarity which scores them independently and compares afterward.

Model: BAAI/bge-reranker-v2-m3 -- CONFIRMED (Sept 2026 search) a
current, well-established open-source cross-encoder, Apache 2.0,
under 600M params, self-hosted (same "no external transmission"
principle as the embedding model). Works directly through
sentence-transformers' CrossEncoder class -- no new dependency beyond
what's already installed for embeddings.

Why this exists: CONFIRMED real baseline problem (see
tests/eval/test_rule_retrieval_eval.py) -- pure cosine similarity has
no sense of query specificity, and a deliberately vague query scored
HIGHER (44%) than a genuinely precise one (34%). A cross-encoder reads
the query and each candidate TOGETHER, which is exactly the signal
pure embedding comparison is missing.

Cost: reranking is meaningfully slower per-candidate than embedding
comparison -- only run it on a SHORTLIST (the top-N from the cheap
embedding search), never the whole corpus.
"""

from __future__ import annotations

import structlog
from sentence_transformers import CrossEncoder

logger = structlog.get_logger(__name__)

RERANKER_MODEL_NAME = "BAAI/bge-reranker-v2-m3"


class Reranker:
    def _get_model(self) -> CrossEncoder:
        from app.ai.retrieval.model_registry import get_shared_reranker_model

        return get_shared_reranker_model()

    def rerank(self, query: str, candidate_texts: list[str]) -> list[float]:
        """Returns one relevance score per candidate, in the SAME
        order as candidate_texts -- higher = more relevant. Caller is
        responsible for re-sorting/truncating using these scores."""
        if not candidate_texts:
            return []
        model = self._get_model()
        pairs = [(query, text) for text in candidate_texts]
        scores = model.predict(pairs)
        raw_scores = [float(s) for s in scores]

        # TEMPORARY -- remove once the "everything shows 50%" issue is diagnosed
        logger.info(
            "reranker_raw_scores",
            query=query,
            raw_scores=raw_scores,
            candidate_count=len(candidate_texts),
        )

        return raw_scores
