from datetime import datetime

from sqlalchemy import ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RuleYamlRepresentation(Base):
    """
    De-identified Sigma-format representation of a QRadar rule --
    'standalone' role has one row per rule; correlation/threshold
    rules split into a 'base' + 'correlation' pair (2 rows sharing
    the same rule_id+customer_id).
    """

    __tablename__ = "rule_yaml_representations"
    __table_args__ = (
        UniqueConstraint("rule_id", "customer_id", "role", name="uq_rule_yaml_rule_customer_role"),
        UniqueConstraint("sigma_id", name="uq_rule_yaml_sigma_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    sigma_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="experimental")
    level: Mapped[str | None] = mapped_column(Text)
    logsource: Mapped[dict | None] = mapped_column(JSONB)
    detection: Mapped[dict] = mapped_column(JSONB, nullable=False)
    tags: Mapped[list | None] = mapped_column(JSONB)
    falsepositives: Mapped[list | None] = mapped_column(JSONB)
    references_: Mapped[list | None] = mapped_column("references", JSONB)
    mitre_techniques_inferred: Mapped[list | None] = mapped_column(JSONB)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default="standalone")
    rule_reference_name: Mapped[str | None] = mapped_column(Text)
    correlation: Mapped[dict | None] = mapped_column(JSONB)
    generated_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    embedded_at: Mapped[datetime | None] = mapped_column()