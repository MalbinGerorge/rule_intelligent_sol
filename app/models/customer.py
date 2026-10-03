from datetime import datetime

from sqlalchemy import Boolean, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.customer_credentials import CustomerCredentials
from app.db.base import Base


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    qradar_host: Mapped[str] = mapped_column(Text, nullable=False)
    verify_ssl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    credentials: Mapped["CustomerCredentials"] = relationship(back_populates="customer", uselist=False)