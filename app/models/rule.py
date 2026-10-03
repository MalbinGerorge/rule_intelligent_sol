from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Rule(Base):
    """Ingested from GET /analytics/rules_with_data (JSON).

    CONFIRMED against real Cotecna data:
      - Every row has TWO ids: `qradar_rule_id` (numeric, e.g. 100001 —
        matches rule_offense_contributions.rule_id and rules_reference.id)
        and `identifier` (string, e.g. "SYSTEM-1443" — used ONLY for the
        per-rule MITRE lookup URL). Don't conflate the two.
      - is_building_block is a real boolean field — object_type is derived
        from THAT, not from parsing the "BB:" name prefix.
      - "Last triggered" is NOT a field on this endpoint — it's derived
        by aggregating rule_offense_contributions.last_event per rule
        (see the planned rule_summary view), so it's deliberately not
        duplicated as a column here.
      - BBs referenced inside a rule's logic show up embedded in raw_json
        (rule_xml) as <userSelection>{identifier}</userSelection> — that's
        how rule_building_blocks gets populated (parsed out separately,
        not stored as its own column here).
    """

    __tablename__ = "rules"
    __table_args__ = (UniqueConstraint("customer_id", "qradar_rule_id", name="uq_rules_customer_ruleid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    qradar_rule_id: Mapped[int] = mapped_column(BigInteger, nullable=False)  # QRadar's numeric "id"
    identifier: Mapped[str | None] = mapped_column(Text, index=True)  # e.g. SYSTEM-1443 — MITRE lookup key
    name: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str | None] = mapped_column(Text)  # EVENT | FLOW | COMMON | USER | ANOMALY | BEHAVIORAL | THRESHOLD
    owner: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str | None] = mapped_column(Text)  # e.g. "SYSTEM" for IBM-default content vs custom rules

    # 'RULE' | 'BUILDING_BLOCK' — derived from the is_building_block boolean during ingestion
    object_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="RULE")
    # e.g. 'HostDefinition', 'CategoryDefinition', 'PortDefinition', 'DeviceDefinition' —
    # only set when object_type = 'BUILDING_BLOCK' (parsed from the "BB:<Subtype>:" name prefix)
    building_block_subtype: Mapped[str | None] = mapped_column(Text)

    enabled: Mapped[bool | None] = mapped_column(Boolean)
    linked_rule_identifier: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))   # from creation_date
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))   # from modification_date
    raw_json: Mapped[dict | None] = mapped_column(JSONB)  # includes rule_xml, capacity fields, etc.
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    offense_contributions: Mapped[list["RuleOffenseContribution"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )
    building_blocks: Mapped[list["RuleBuildingBlock"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )
    mitre_mappings: Mapped[list["MitreMapping"]] = relationship(back_populates="rule")