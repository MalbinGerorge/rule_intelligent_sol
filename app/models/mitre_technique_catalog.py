from datetime import datetime

from sqlalchemy import Boolean, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MitreTechniqueCatalog(Base):
    """The FULL official MITRE ATT&CK catalog -- NOT customer-scoped,
    a single shared reference table refreshed periodically from
    MITRE's own public data (see scripts/sync_mitre_catalog.py)."""

    __tablename__ = "mitre_technique_catalog"
    __table_args__ = (
        UniqueConstraint("technique_id", name="uq_mitre_technique_catalog_technique_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    technique_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    technique_name: Mapped[str | None] = mapped_column(Text)
    tactic_names: Mapped[list | None] = mapped_column(ARRAY(Text))
    is_subtechnique: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    parent_technique_id: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
