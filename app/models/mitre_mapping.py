from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MitreMapping(Base):
    """From the Use Case Manager app proxy (/console/plugins/app_proxy:UseCaseManager_Service).

    One row per (rule, tactic, technique) — a tactic with no specific
    technique (e.g. "Credential Access" with an empty techniques dict)
    still gets a row, with technique_id/technique_name as '' rather than
    NULL. This is deliberate: Postgres treats NULL as distinct from NULL
    in unique constraints, which would let ON CONFLICT silently fail to
    dedupe tactic-only rows on repeated ingestion runs. Empty string is
    a real, comparable value, so the constraint (and re-run dedup) works.
    """

    __tablename__ = "mitre_mappings"
    __table_args__ = (
        UniqueConstraint(
            "rule_id", "tactic_id", "technique_id", name="uq_mitre_mappings_rule_tactic_technique"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("rules.id", ondelete="CASCADE"), index=True)
    tactic_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="")  # e.g. TA0006
    tactic: Mapped[str | None] = mapped_column(Text)                                 # e.g. Credential Access
    technique_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="")    # e.g. T1030
    technique_name: Mapped[str | None] = mapped_column(Text)                              # e.g. Steal or Forge Kerberos Tickets
    raw_json: Mapped[dict | None] = mapped_column(JSONB)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    rule: Mapped["Rule"] = relationship(back_populates="mitre_mappings")