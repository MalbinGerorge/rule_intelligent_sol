from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MitreTactic(Base):
    """MITRE ATT&CK tactics as MITRE publishes them (e.g. TA0005 "Stealth",
    STIX short name "stealth"). Not customer-scoped; refreshed with the
    technique catalog (app/ingestion/jobs/mitre_catalog_sync.py)."""

    __tablename__ = "mitre_tactics"
    __table_args__ = (
        CheckConstraint(r"tactic_id ~ '^TA[0-9]{4}$'", name="ck_mitre_tactics_tactic_id_format"),
        UniqueConstraint("name", name="uq_mitre_tactics_name"),
        UniqueConstraint("shortname", name="uq_mitre_tactics_shortname"),
    )

    tactic_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    shortname: Mapped[str] = mapped_column(Text, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
