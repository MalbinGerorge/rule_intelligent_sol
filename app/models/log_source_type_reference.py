from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LogSourceTypeReference(Base):
    """
    Reference table for log source TYPES (not individual configured log
    sources) — pulled once from QRadar's log_source_types endpoint,
    cached here, used to resolve DeviceTypeID_Test's numeric type codes
    to real names. Same pattern as rules_reference/mitre_mappings: pull
    once, cache locally, join against it instead of hitting the API
    every time a code needs resolving.
    """

    __tablename__ = "log_source_types_reference"
    __table_args__ = (UniqueConstraint("customer_id", "qradar_type_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    qradar_type_id: Mapped[int] = mapped_column(BigInteger, nullable=False)  # QRadar's numeric "id"
    name: Mapped[str | None] = mapped_column(Text, index=True)
    custom: Mapped[bool | None] = mapped_column(Boolean)
    internal: Mapped[bool | None] = mapped_column(Boolean)
    raw_json: Mapped[dict | None] = mapped_column(JSONB)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())