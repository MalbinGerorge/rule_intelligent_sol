from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CustomerCredentials(Base):
    __tablename__ = "customer_credentials"

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), primary_key=True
    )
    token_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    rotated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    customer: Mapped["Customer"] = relationship(back_populates="customer")