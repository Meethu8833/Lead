"""
app/models/payment.py

SQLAlchemy model for Payment.
"""

from __future__ import annotations
import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Numeric, DateTime, Enum, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.order import Order


class PaymentMethod(str, enum.Enum):
    CASH = "CASH"
    UPI = "UPI"
    BANK_TRANSFER = "BANK_TRANSFER"
    CARD = "CARD"
    CHEQUE = "CHEQUE"
    OTHER = "OTHER"


class Payment(Base):
    __tablename__ = "payments"
    
    __table_args__ = (
        CheckConstraint("amount > 0", name="chk_payment_amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier for the payment (UUIDv4)"
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        doc="Reference to the order being paid for"
    )

    amount: Mapped[float] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        doc="Payment amount received"
    )

    payment_method: Mapped[PaymentMethod] = mapped_column(
        Enum(PaymentMethod, name="paymentmethod"),
        nullable=False,
        doc="Method used for payment (CASH, UPI, etc.)"
    )

    reference_number: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        doc="Payment transaction reference, transaction ID, cheque number, etc."
    )

    remarks: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Additional comments or notes about the payment"
    )

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Timestamp when the payment was received by the system"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="System creation timestamp"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="System last update timestamp"
    )

    # Relationships
    order: Mapped["Order"] = relationship(
        "Order",
        back_populates="payments"
    )
