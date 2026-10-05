"""
Shared, process-wide singletons for the embedding and reranker
models. CONFIRMED REAL BUG this fixes: SimilaritySearchService was
creating a fresh Reranker() and reloading its embedding model from
scratch on EVERY single request (a new service instance per HTTP
call, with no caching between requests) -- this caused both extreme
per-request latency (minutes, not seconds -- the "duration" was
mostly model RELOADING, not actual search work) and a genuine
out-of-memory crash (Windows OSError 1455, "paging file too small")
when two overlapping requests each tried to hold a full model copy in
memory at once.

Fix: load each model exactly ONCE, on first use, and hold it here for
the lifetime of the process -- every subsequent request reuses the
SAME already-loaded object. Same principle as a database connection
pool -- expensive-to-create resources are shared, not recreated per
request.
"""

from __future__ import annotations

import threading

from sentence_transformers import CrossEncoder, SentenceTransformer

from app.recommendations.embedding_service import EMBEDDING_MODEL_NAME
from app.recommendations.reranker import RERANKER_MODEL_NAME

_embedding_model: SentenceTransformer | None = None
_reranker_model: CrossEncoder | None = None
_lock = threading.Lock()  # guards against two threads racing to load the same model twice


def get_shared_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        with _lock:
            if (
                _embedding_model is None
            ):  # re-check inside the lock -- another thread may have just finished loading
                _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _embedding_model


def get_shared_reranker_model() -> CrossEncoder:
    global _reranker_model
    if _reranker_model is None:
        with _lock:
            if _reranker_model is None:
                _reranker_model = CrossEncoder(RERANKER_MODEL_NAME)
    return _reranker_model
