"""
Generates and stores embeddings for de-identified Sigma rule
representations, for INTENT-based similarity search across customers
-- distinct from LogSourceGapAnalyzer/MitreGapAnalyzer's exact
category matching.

Model: Qwen3-Embedding-0.6B -- CONFIRMED (Jan 2026 MTEB retrieval
snapshot) top-ranked open-source retrieval model, self-hosted, no
external API calls -- same "no external transmission" principle
already used for Sigma generation itself.

Staleness: embedded_at vs generated_at on rule_yaml_representations
-- mirrors rules.needs_reparse's principle exactly. Covers BOTH a
QRadar-side rule change AND a manual Sigma re-run after a prompt fix,
since generated_at already reflects either case uniformly.

Confidentiality boundary: embeds ONLY title/description/detection
content already in rule_yaml_representations -- the SAME boundary
already enforced by LogSourceGapAnalyzer/MitreGapAnalyzer's
_build_suggestions(). Deliberately coupled to Sigma's own quality --
see project notes: the alternative (embedding raw, non-de-identified
data) would be a real confidentiality regression, not an improvement.
"""

from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = structlog.get_logger(__name__)

EMBEDDING_MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"
CHROMA_COLLECTION_NAME = "sigma_rules"


def get_stale_representations(db: Session) -> list[dict]:
    """Representations needing a fresh embedding -- never embedded
    yet, OR embedded before the current Sigma content was generated.
    Spans ALL customers deliberately -- this is a shared, cross-
    customer search index, not a per-customer job like Sigma
    generation itself."""
    rows = (
        db.execute(
            text(
                """
            SELECT ryr.rule_id, ryr.customer_id, c.name AS customer_name,
                   ryr.title, ryr.description, ryr.detection, ryr.level, ryr.tags
            FROM rule_yaml_representations ryr
            JOIN customers c ON c.id = ryr.customer_id
            WHERE ryr.role IN ('standalone', 'base')
              AND (ryr.embedded_at IS NULL OR ryr.embedded_at < ryr.generated_at)
            """
            )
        )
        .mappings()
        .all()
    )
    logger.info("stale_representations_found", count=len(rows))
    return [dict(r) for r in rows]


def build_embedding_text(row: dict) -> str:
    """Combines the parts of a Sigma representation that carry real
    INTENT -- title, description, and the condition string -- into
    one text block. Raw field/value pairs are deliberately excluded;
    they're structural detail, not intent."""
    parts = [row["title"] or ""]
    if row["description"]:
        parts.append(row["description"])
    detection = row["detection"] or {}
    condition = detection.get("condition")
    if condition:
        parts.append(f"Detection logic: {condition}")
    return "\n".join(parts)


def mark_embedded(db: Session, rule_id: int, customer_id: int) -> None:
    db.execute(
        text(
            """
            UPDATE rule_yaml_representations
            SET embedded_at = now()
            WHERE rule_id = :rule_id AND customer_id = :customer_id
              AND role IN ('standalone', 'base')
            """
        ),
        {"rule_id": rule_id, "customer_id": customer_id},
    )
