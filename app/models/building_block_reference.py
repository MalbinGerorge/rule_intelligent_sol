from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BuildingBlockReference(Base):
    """Ground truth from /analytics/building_blocks (JSON).

    CONFIRMED same shape as rules_reference (owner, identifier,
    base_host_id, capacity_timestamp, origin, creation_date, type,
    enabled, modification_date, linked_rule_identifier, name,
    average_capacity, id, base_capacity) — and CONFIRMED these rows are
    literally the same underlying objects as the is_building_block=true
    subset of rules_with_data (matching id + identifier in both).
    qradar_rule_id here is that same numeric "id".
    """

    __tablename__ = "building_blocks_reference"
    __table_args__ = (
        UniqueConstraint("customer_id", "qradar_rule_id", name="uq_bb_reference_customer_ruleid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    qradar_rule_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    identifier: Mapped[str | None] = mapped_column(Text, index=True)
    name: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[dict | None] = mapped_column(JSONB)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())