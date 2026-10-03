from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RuleMitreUnified(Base):
    """A REAL table (not a view), refreshed explicitly via
    sync_rule_mitre_unified() -- combines QRadar-confirmed
    (mitre_source='confirmed') and LLM-inferred
    (mitre_source='derived') technique mappings into one queryable
    shape. See app/services/mitre_unified_sync.py."""

    __tablename__ = "rule_mitre_unified"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(nullable=False, index=True)
    tactic: Mapped[str | None] = mapped_column(Text)
    technique_id: Mapped[str | None] = mapped_column(Text, index=True)
    technique_name: Mapped[str | None] = mapped_column(Text)
    mitre_source: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[str | None] = mapped_column(Text)