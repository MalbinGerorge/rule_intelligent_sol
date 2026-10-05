"""
Automated evaluation for rule similarity search -- runs REAL
questions against the REAL SimilaritySearchService (Postgres +
ChromaDB + Qwen3-Embedding-0.6B). Deliberately an INTEGRATION test,
not a unit test with mocks -- the entire point is measuring real
retrieval QUALITY, which mocks can't tell us anything about.

Uses the SAME structured logging as the real app (app/core/logging.py)
-- every case's real outcome (question, hit/miss, top score, latency)
gets written to BOTH console and the rotating logs/app.log file,
timestamp-first. This means eval RESULTS accumulate as a real,
searchable history over time in the same log file as production
traffic -- not just whatever pytest happens to print once and forget.

Two genuinely different kinds of cases here, on purpose:
  - EVAL_CASES: "did it find a genuinely relevant rule" -- standard
    hit-rate checks, confirmed against real manual testing.
  - VAGUE_QUERY_CASES: "did it stay appropriately UNCONFIDENT on a
    bad/vague query" -- a different failure mode entirely. CONFIRMED
    REAL BASELINE PROBLEM: a vague query ("suspicious activity on a
    server") scored HIGHER (44%) than a genuinely precise one (34%)
    -- pure cosine similarity has no sense of "was this query specific
    enough to deserve a confident answer." This is the concrete
    evidence motivating the reranker. Marked xfail deliberately: it's
    a KNOWN, TRACKED limitation of the current baseline, not a silent
    or accidental failure -- remove the xfail once the reranker fixes
    it, and its result becomes the real, measurable proof of
    improvement.

Run: uv run pytest evals/retrieval/test_rule_retrieval_eval.py -v -s
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest
import structlog
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.ai.retrieval.similarity_search import SimilaritySearchService
from app.core.logging import configure_logging
from app.db.session import engine

logger = structlog.get_logger("eval.rule_retrieval")

# The QUERYING customer -- its OWN rules get excluded from results
# (see SimilaritySearchService). "all cargo" is used here since
# Cotecna's real Sysmon rules are the expected peer matches below,
# confirmed via real manual testing.
TEST_CUSTOMER_NAME = "all cargo"

EVAL_CASES = [
    {
        "id": "process_injection_remote_thread",
        "question": 'Extra Window Memory Injection"/"Remote Thread Creation',
        "expected_title_substrings": ["Remote Thread", "Injection"],
        # CONFIRMED real baseline result (manual test): top match
        # scored 34% -- set slightly below that as a regression guard.
        "min_top_score": 0.25,
    },
    {
        "id": "malware_injection_into_running_process",
        "question": "malware injecting code into another running process",
        "expected_title_substrings": ["CrowdStrike", "Injection"],
        # CONFIRMED real result (manual test, after lowering
        # MIN_RAW_RERANK_SCORE to 0.01): top match "CrowdStrike Defense
        # Evasion via Process Injection Detection" scored 50%. This
        # case exists specifically to catch a regression of the exact
        # bug just fixed: a genuine match (raw rerank score 0.015) was
        # being wrongly excluded when MIN_RAW_RERANK_SCORE was 0.1.
        "min_top_score": 0.45,
    },
]

VAGUE_QUERY_CASES = [
    {
        "id": "vague_suspicious_activity",
        "question": "suspicious activity on a server",
        # CONFIRMED baseline currently returns ~0.44 (a generic recon/
        # port-scan rule) -- should drop once reranking is added.
        "max_acceptable_top_score": 0.30,
    },
]


@pytest.fixture(scope="session", autouse=True)
def _configure_eval_logging():
    """Wires the SAME structured logging as the real app into this
    eval run, once, before any test -- timestamped, JSON-file +
    readable console, exactly like production traffic."""
    configure_logging(log_level="INFO")


@pytest.fixture(scope="module")
def search_service():
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    yield SimilaritySearchService(db)
    db.close()


@pytest.fixture(scope="module")
def customer_id(search_service):
    row = search_service.db.execute(
        text("SELECT id FROM customers WHERE name = :name"), {"name": TEST_CUSTOMER_NAME}
    ).scalar_one_or_none()
    if row is None:
        pytest.skip(f"Test customer '{TEST_CUSTOMER_NAME}' not found -- adjust TEST_CUSTOMER_NAME")
    return row


def _hit(result_titles: list[str], expected_substrings: list[str]) -> bool:
    joined = " | ".join(t.lower() for t in result_titles)
    return any(sub.lower() in joined for sub in expected_substrings)


def _run_and_log(
    search_service, customer_id: int, case: dict, event_name: str
) -> tuple[list[str], float | None, float]:
    """Runs the real search, logs a full structured record of the
    outcome (question, result titles, top score, latency), and
    returns what the calling test needs to make its assertions."""
    started_at = time.perf_counter()
    results = search_service.search(customer_id, case["question"], top_k=5)
    duration_ms = round((time.perf_counter() - started_at) * 1000, 1)

    result_titles = [r.title for r in results]
    top_score = results[0].similarity_score if results else None

    logger.info(
        event_name,
        case_id=case["id"],
        question=case["question"],
        result_titles=result_titles,
        top_score=top_score,
        result_count=len(results),
        duration_ms=duration_ms,
    )

    return result_titles, top_score, duration_ms


@pytest.mark.parametrize("case", EVAL_CASES, ids=[c["id"] for c in EVAL_CASES])
def test_retrieval_hit_at_5(search_service, customer_id, case):
    result_titles, top_score, _ = _run_and_log(
        search_service, customer_id, case, "eval_hit_case_completed"
    )

    assert _hit(result_titles, case["expected_title_substrings"]), (
        f"Expected one of {case['expected_title_substrings']} in top 5 results, got: {result_titles}"
    )
    if case["min_top_score"] is not None and top_score is not None:
        assert top_score >= case["min_top_score"], (
            f"Top score {top_score} fell below the confirmed baseline of {case['min_top_score']}"
        )


@pytest.mark.xfail(
    reason="CONFIRMED baseline limitation: vague queries currently score HIGHER "
    "than precise ones (pure cosine similarity has no sense of query specificity). "
    "This is the real motivating case for the reranker -- remove xfail once fixed."
)
@pytest.mark.parametrize("case", VAGUE_QUERY_CASES, ids=[c["id"] for c in VAGUE_QUERY_CASES])
def test_vague_query_stays_low_confidence(search_service, customer_id, case):
    _, top_score, _ = _run_and_log(search_service, customer_id, case, "eval_vague_case_completed")

    if top_score is None:
        return  # no results at all is ALSO an acceptable outcome for a vague query
    assert top_score <= case["max_acceptable_top_score"], (
        f"Vague query scored {top_score} (confident) -- expected <= {case['max_acceptable_top_score']}"
    )
