"""
Synchronous intent-based similarity search over embedded Sigma rules,
with cross-encoder RERANKING as a second, more accurate pass.

Two-stage pipeline:
  1. Embedding (cheap, broad): fetch a wide candidate SHORTLIST via
     Chroma cosine similarity -- fast, but CONFIRMED (see
     tests/eval/test_rule_retrieval_eval.py) to have no sense of
     query specificity: a vague query can score HIGHER than a precise
     one.
  2. Reranking (slower, accurate): re-score each (query, candidate)
     pair TOGETHER via a cross-encoder -- reads them jointly, unlike
     step 1's independent-then-compare approach. Only run on the
     shortlist from step 1, never the whole corpus -- this is what
     keeps it fast enough to run inline in a request.

Candidates with a genuinely low RAW rerank score are EXCLUDED
entirely, not shown with a softened/misleading score. CONFIRMED real
bug this fixes: sigmoid(near-zero raw score) rounds to the same 50%
for wildly different, genuinely unrelated candidates (observed
directly: a "palo alto" query returned 5 completely unrelated rules,
all displaying "50% match"). Declining to show a candidate the model
itself judged as irrelevant is more honest than relabeling it.

Both scores are kept on every PeerRuleSuggestion (embedding_score =
raw step 1, similarity_score = FINAL, reranked step 2) -- never
silently overwritten, so the reranker's actual effect stays visible
and comparable, not hidden.

Excludes the REQUESTING customer's own rules from results -- the
whole point is checking what PEERS have already built before writing
a rule from scratch, not re-surfacing the customer's own existing
content.

Confidentiality boundary: SAME as LogSourceGapAnalyzer/MitreGapAnalyzer
-- pulls ONLY de-identified content from rule_yaml_representations,
never raw rule_conditions.
"""

from __future__ import annotations

import math
import time

import chromadb
import structlog
from sentence_transformers import SentenceTransformer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.schemas.recommendations import PeerRuleSuggestion, SimilaritySearchResult
from app.core.config import settings
from app.recommendations.embedding_service import CHROMA_COLLECTION_NAME, build_embedding_text
from app.recommendations.reranker import Reranker

logger = structlog.get_logger(__name__)

# How much wider than top_k the initial embedding shortlist is, before
# reranking narrows it back down -- reranking needs a broader pool to
# actually have candidates worth promoting/demoting.
RERANK_POOL_MULTIPLIER = 5

# Minimum RAW (pre-sigmoid) cross-encoder score for a candidate to be
# shown at all. CONFIRMED from real data: genuine matches produced raw
# scores around 0.69-0.97; a genuinely irrelevant query ("rules
# related to palo alto" against unrelated storage/offense rules)
# produced raw scores of 0.0000175-0.00018 -- a ~4-order-of-magnitude
# gap. 0.1 sits well below the real-match range and well above the
# noise range observed so far. Worth refining with the eval harness
# as more real query patterns are tested -- not a final, fixed number.
MIN_RAW_RERANK_SCORE = 0.01


def _sigmoid(x: float) -> float:
    """Squashes a raw cross-encoder logit into a 0-1 range, matching
    embedding_score's scale for direct comparison. NOTE: the exact
    output characteristics of BAAI/bge-reranker-v2-m3 should be
    verified empirically once run against real data -- this is
    standard practice for cross-encoder logits, not a value confirmed
    against this specific model's real output range yet."""
    return 1 / (1 + math.exp(-x))


class SimilaritySearchService:
    def __init__(self, db: Session, reranker: Reranker | None = None):
        self.db = db
        self.reranker = reranker or Reranker()
        self._collection = None

    def _get_model(self) -> SentenceTransformer:
        from app.recommendations.model_registry import get_shared_embedding_model

        return get_shared_embedding_model()

    def _get_collection(self):
        if self._collection is None:
            client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
            self._collection = client.get_or_create_collection(CHROMA_COLLECTION_NAME)
        return self._collection

    def search(self, customer_id: int, query: str, top_k: int = 5) -> SimilaritySearchResult:
        started_at = time.perf_counter()
        model = self._get_model()
        collection = self._get_collection()

        query_embedding = model.encode([query]).tolist()

        # Stage 1: wide, cheap embedding shortlist -- NOT the final
        # answer, just a candidate pool for stage 2 to actually judge.
        pool_size = top_k * RERANK_POOL_MULTIPLIER
        results = collection.query(query_embeddings=query_embedding, n_results=pool_size)

        if not results["ids"] or not results["ids"][0]:
            return SimilaritySearchResult(results=[], excluded_low_relevance=0)

        candidate_rule_ids: list[int] = []
        meta_by_rule_id: dict[int, dict] = {}
        for i, meta in enumerate(results["metadatas"][0]):
            if meta["customer_id"] == customer_id:
                continue  # exclude the requesting customer's own rules
            rid = meta["rule_id"]
            candidate_rule_ids.append(rid)
            meta_by_rule_id[rid] = {**meta, "distance": results["distances"][0][i]}

        if not candidate_rule_ids:
            return SimilaritySearchResult(results=[], excluded_low_relevance=0)

        logger.info(
            "embedding_shortlist_retrieved",
            query=query,
            candidate_count=len(candidate_rule_ids),
            candidates=[
                {
                    "rule_id": rid,
                    "title": meta_by_rule_id[rid].get("title"),
                    "embedding_score": round(1 - meta_by_rule_id[rid]["distance"], 3),
                }
                for rid in candidate_rule_ids
            ],
        )

        rows = (
            self.db.execute(
                text(
                    """
                SELECT rule_id, title, description, level, detection, tags
                FROM rule_yaml_representations
                WHERE rule_id = ANY(:rule_ids) AND role IN ('standalone', 'base')
                """
                ),
                {"rule_ids": candidate_rule_ids},
            )
            .mappings()
            .all()
        )

        # Stage 2: rerank the WHOLE shortlist -- same text
        # representation as embedding generation, for consistency.
        rows_dicts = [dict(r) for r in rows]
        candidate_texts = [build_embedding_text(r) for r in rows_dicts]
        raw_rerank_scores = self.reranker.rerank(query, candidate_texts)
        # strict=True: one score per candidate is required -- a length
        # mismatch must fail loudly, not silently drop candidates.
        raw_rerank_score_by_rule_id = {
            r["rule_id"]: s for r, s in zip(rows_dicts, raw_rerank_scores, strict=True)
        }
        rerank_score_by_rule_id = {
            r["rule_id"]: _sigmoid(s) for r, s in zip(rows_dicts, raw_rerank_scores, strict=True)
        }

        suggestions = []
        excluded_low_relevance = 0
        for row in rows_dicts:
            raw_score = raw_rerank_score_by_rule_id.get(row["rule_id"])

            # Honestly decline to show a candidate the reranker judged
            # as genuinely irrelevant -- confirmed better than showing
            # it with a misleading, flattened score (see project notes:
            # sigmoid(near-zero) rounds to the SAME 50% for wildly
            # different, unrelated candidates).
            if raw_score is not None and raw_score < MIN_RAW_RERANK_SCORE:
                excluded_low_relevance += 1
                continue

            meta = meta_by_rule_id.get(row["rule_id"], {})
            distance = meta.get("distance", 1.0)
            embedding_score = round(1 - distance, 3)
            rerank_score = rerank_score_by_rule_id.get(row["rule_id"])
            final_score = round(rerank_score, 3) if rerank_score is not None else embedding_score

            suggestions.append(
                PeerRuleSuggestion(
                    source_customer_name=meta.get("customer_name", "unknown"),
                    rule_id=row["rule_id"],
                    title=row["title"],
                    description=row["description"],
                    level=row["level"],
                    detection=row["detection"],
                    tags=row["tags"] or [],
                    similarity_score=final_score,
                    embedding_score=embedding_score,
                )
            )

        # Sort and truncate AFTER reranking -- a candidate outside the
        # original embedding top-K can still surface here if the
        # reranker judges it genuinely more relevant.
        suggestions.sort(key=lambda s: s.similarity_score or 0, reverse=True)
        suggestions = suggestions[:top_k]

        duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
        logger.info(
            "similarity_search_completed",
            customer_id=customer_id,
            query=query,
            result_count=len(suggestions),
            excluded_low_relevance=excluded_low_relevance,
            duration_ms=duration_ms,
        )
        return SimilaritySearchResult(
            results=suggestions, excluded_low_relevance=excluded_low_relevance
        )
