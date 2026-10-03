from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RuleCondition(Base):
    """
    One row per <test> element (excluding BB/rule-reference tests already
    captured in rule_building_blocks — see rule_condition_parser.py).

    structured_data is JSONB rather than fixed columns because ~50+
    different test classes each produce a different shape (a threshold
    dict, an Ariel field/operator/values, a generic parameter list) —
    same flexible-schema pattern already used for rules.raw_json etc.
    """

    __tablename__ = "rule_conditions"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("rules.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False)  # position within the rule's <testDefinitions>
    test_class: Mapped[str] = mapped_column(Text, nullable=False)
    negated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw_text: Mapped[str | None] = mapped_column(Text)  # QRadar's own plain-English sentence, tags stripped
    structured_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    rule: Mapped["Rule"] = relationship()