from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LogSourceReference(Base):
    """
    Reference table for CONFIGURED log source INSTANCES (not types) --
    pulled from QRadar's log_sources endpoint. This is the genuine
    "onboarded" signal -- a log_source_types_reference entry only means
    QRadar's SOFTWARE supports parsing that vendor/product; a row HERE
    means an actual instance was configured on this customer's console.

    CONFIRMED REAL BUG this table fixes: log_source_types_reference
    alone returned "Citrix NetScaler" / "McAfee NSP" as "onboarded" for
    a real customer, even though zero actual log sources of those types
    exist on their real console -- log_source_types is QRadar's full
    supported-DSM catalog, identical across every deployment, not
    customer-specific data.
    """

    __tablename__ = "log_sources_reference"
    __table_args__ = (UniqueConstraint("customer_id", "qradar_log_source_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    qradar_log_source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    type_id: Mapped[int | None] = mapped_column(BigInteger, index=True)  # links to log_source_types_reference.qradar_type_id
    enabled: Mapped[bool | None] = mapped_column(Boolean)
    status: Mapped[str | None] = mapped_column(Text)  # from status.status
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    average_eps: Mapped[float | None] = mapped_column(Float)
    raw_json: Mapped[dict | None] = mapped_column(JSONB)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())