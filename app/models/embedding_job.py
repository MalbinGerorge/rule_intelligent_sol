from datetime import datetime

from sqlalchemy import Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EmbeddingJob(Base):
    """Not customer-scoped -- embedding generation spans a SHARED,
    cross-customer search index (see embedding_service.py)."""

    __tablename__ = "embedding_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="running", index=True)
    total_representations: Mapped[int] = mapped_column(server_default="0", nullable=False)
    processed_representations: Mapped[int] = mapped_column(server_default="0", nullable=False)
    failed_representations: Mapped[int] = mapped_column(server_default="0", nullable=False)
    failed_details: Mapped[list | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column()