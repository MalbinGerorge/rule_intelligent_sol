from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ValidationResult(Base):
    """Generalized cross-check results, covering both the rules pipeline
    (entity_type='rule') and the building blocks pipeline
    (entity_type='building_block')."""

    __tablename__ = "validation_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)  # 'rule' | 'building_block'
    entity_ref: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    check_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # 'pass' | 'fail' | 'missing'
    details: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())