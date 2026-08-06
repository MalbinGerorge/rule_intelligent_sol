from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RuleBuildingBlock(Base):
    """Building blocks referenced inside a rule's XML test conditions,
    extracted during ingestion of rules_with_data. Validated against
    BuildingBlockReference."""

    __tablename__ = "rule_building_blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("rules.id", ondelete="CASCADE"), nullable=False, index=True)
    bb_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    raw_xml_snippet: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    rule: Mapped["Rule"] = relationship(back_populates="building_blocks")