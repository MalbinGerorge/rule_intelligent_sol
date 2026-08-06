from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RuleOffenseContribution(Base):
    """Ingested from GET /analytics/rules_offense_contributions (JSON —
    not XML, corrected per real QRadar API docs).

    customer_id + unique(customer_id, qradar_contribution_id) added so
    re-running ingestion upserts instead of creating duplicate rows —
    the API's own "id" field is the natural dedup key here.

    first_event / last_event are stored both as the raw epoch-millisecond
    Long QRadar returns (*_epoch_ms) and as a converted TIMESTAMPTZ, so
    nothing is lost if the conversion assumption turns out wrong.
    """

    __tablename__ = "rule_offense_contributions"
    __table_args__ = (
        UniqueConstraint(
            "customer_id", "qradar_contribution_id", name="uq_offense_contrib_customer_contribid"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("rules.id", ondelete="CASCADE"), nullable=False, index=True)

    qradar_contribution_id: Mapped[int] = mapped_column(BigInteger, nullable=False)  # API's own "id"
    qradar_rule_id: Mapped[int | None] = mapped_column(BigInteger)  # API's "rule_id" — CONFIRMED same
    # numeric ID space as rules.qradar_rule_id (verified against real Cotecna data: custom rule
    # IDs like 108042 here match the same range as rules_with_data's "id" field)
    rule_name: Mapped[str | None] = mapped_column(Text)
    rule_type: Mapped[str | None] = mapped_column(Text)  # EVENT | FLOW | COMMON | USER | ANOMALY | BEHAVIORAL | THRESHOLD
    offense_id: Mapped[str | None] = mapped_column(Text)
    event_count: Mapped[int | None] = mapped_column(Integer)

    first_event_epoch_ms: Mapped[int | None] = mapped_column(BigInteger)
    last_event_epoch_ms: Mapped[int | None] = mapped_column(BigInteger)
    first_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    raw_json: Mapped[dict | None] = mapped_column(JSONB)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    rule: Mapped["Rule"] = relationship(back_populates="offense_contributions")