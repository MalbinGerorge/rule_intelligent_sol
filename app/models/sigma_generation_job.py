from datetime import datetime

from sqlalchemy import ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SigmaGenerationJob(Base):
    __tablename__ = "sigma_generation_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="running", index=True)
    requested_rule_names: Mapped[list | None] = mapped_column(JSONB)
    total_rules: Mapped[int] = mapped_column(server_default="0", nullable=False)
    processed_rules: Mapped[int] = mapped_column(server_default="0", nullable=False)
    failed_rules: Mapped[int] = mapped_column(server_default="0", nullable=False)
    failed_rule_details: Mapped[list | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column()