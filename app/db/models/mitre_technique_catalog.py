from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MitreTechniqueCatalog(Base):
    """The FULL official MITRE ATT&CK catalog -- NOT customer-scoped,
    a single shared reference table refreshed periodically from
    MITRE's own public data (app/ingestion/jobs/mitre_catalog_sync.py).

    Holds every technique MITRE publishes, including revoked and deprecated
    ones (QRadar still maps rules to some revoked IDs); readers that want
    the current catalog filter on status = 'active'. A revoked technique
    points at its replacement in replaced_by_technique_id."""

    __tablename__ = "mitre_technique_catalog"
    __table_args__ = (
        UniqueConstraint("technique_id", name="uq_mitre_technique_catalog_technique_id"),
        CheckConstraint(
            "status IN ('active', 'deprecated', 'revoked')",
            name="ck_mitre_technique_catalog_status",
        ),
        CheckConstraint(
            "replaced_by_technique_id IS NULL OR status = 'revoked'",
            name="ck_mitre_technique_catalog_replaced_only_if_revoked",
        ),
        CheckConstraint(
            r"technique_id ~ '^T[0-9]{4}(\.[0-9]{3})?$'",
            name="ck_mitre_technique_catalog_technique_id_format",
        ),
        CheckConstraint(
            "is_subtechnique = (parent_technique_id IS NOT NULL)",
            name="ck_mitre_technique_catalog_subtechnique_has_parent",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    technique_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    technique_name: Mapped[str | None] = mapped_column(Text)
    tactic_names: Mapped[list | None] = mapped_column(ARRAY(Text))
    is_subtechnique: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    parent_technique_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    replaced_by_technique_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey(
            "mitre_technique_catalog.technique_id",
            name="fk_mitre_technique_catalog_replaced_by",
            ondelete="SET NULL",
        ),
    )
    synced_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
