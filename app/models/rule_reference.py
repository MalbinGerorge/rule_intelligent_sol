from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RuleReference(Base):
    """Ground truth from /analytics/rules (JSON). Used only to validate
    `rules` — confirmed same shape as building_blocks_reference (both
    rules and BBs come back unflagged, mixed together, here). Kept lean
    (existence-check purpose only); raw_json holds everything else."""

    __tablename__ = "rules_reference"
    __table_args__ = (
        UniqueConstraint("customer_id", "qradar_rule_id", name="uq_rules_reference_customer_ruleid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    qradar_rule_id: Mapped[int] = mapped_column(BigInteger, nullable=False)  # QRadar's numeric "id"
    identifier: Mapped[str | None] = mapped_column(Text, index=True)
    name: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[dict | None] = mapped_column(JSONB)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())