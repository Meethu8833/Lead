"""
app/models/order.py

This file defines the SQLAlchemy database model for the Order entity and the OrderStatus enum.
Under Clean Architecture, this file belongs to the Enterprise Domain Model layer.
It represents the persistent structure of the Order domain entity in PostgreSQL.
"""

from __future__ import annotations
import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Integer, Numeric, DateTime, Text, Enum, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.database import Base

from app.models.payment import Payment
from app.models.invoice import Invoice
from app.models.delivery import Delivery
from app.models.notification import NotificationLog

if TYPE_CHECKING:
    from app.models.photographer import Photographer
    from app.models.order_item import OrderItem


class OrderStatus(str, enum.Enum):
    """
    Enum representing the lifecycle status of a Colour Lab order.
    """
    RECEIVED = "RECEIVED"
    DESIGNING = "DESIGNING"
    EDITING = "EDITING"
    COLOR_CORRECTION = "COLOR_CORRECTION"
    PRINTING = "PRINTING"
    LAMINATION = "LAMINATION"
    QUALITY_CHECK = "QUALITY_CHECK"
    PACKING = "PACKING"
    READY = "READY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, enum.Enum):
    """
    Enum representing the payment status of an order.
    """
    PENDING = "PENDING"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    FULLY_PAID = "FULLY_PAID"
    OVERPAID = "OVERPAID"


class Order(Base):
    """
    Order database model.
    Represents the database structure of an order placed by a photographer in PostgreSQL.

    Design Decisions:
    - Primary Key ID: UUIDv4 is used instead of sequential integers to:
      1. Prevent URL resource enumeration vulnerability.
      2. Prevent id collisions across environments or migrations.
    - Foreign Key: photographer_id maps to photographers.id, establishing a One-to-Many relationship.
    - order_number: Indexed and unique field representing the human-readable identifier.
    - Financial fields: Stored as Numeric/Decimal to prevent floating point inaccuracies.
    """
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier for the order (UUIDv4)"
    )

    photographer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("photographers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        doc="Reference to the photographer who placed the order"
    )

    order_number: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        doc="Unique automatically generated order number (e.g. ORD-2026-000001)"
    )

    job_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Descriptive name of the photography job"
    )

    event_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        doc="Type of the event (e.g., Wedding, Pre-wedding, Birthday)"
    )



    # Dates
    booking_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        doc="Timestamp representing when the order was booked"
    )

    event_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp of the event date"
    )

    expected_delivery_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        doc="Expected completion and delivery timestamp"
    )

    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp of when the order was delivered"
    )

    # Financial (Numeric is preferred for currency to avoid floating-point errors)
    total_amount: Mapped[float] = mapped_column(
        Numeric(10, 2),
        default=0.00,
        nullable=False,
        doc="Total price of the order"
    )

    advance_paid: Mapped[float] = mapped_column(
        Numeric(10, 2),
        default=0.00,
        nullable=False,
        doc="Advance payment received from the photographer"
    )

    _balance_amount: Mapped[float] = mapped_column(
        "balance_amount",
        Numeric(10, 2),
        default=0.00,
        nullable=False,
        doc="Remaining balance amount to be paid (stored for legacy but calculated dynamically)"
    )

    payment_status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="paymentstatus"),
        default=PaymentStatus.PENDING,
        server_default=PaymentStatus.PENDING.value,
        nullable=False,
        index=True,
        doc="Payment status of the order"
    )

    @property
    def balance_amount(self) -> float:
        total_paid = sum(float(p.amount) for p in self.payments)
        return round(float(self.total_amount) - total_paid, 2)

    @balance_amount.setter
    def balance_amount(self, value: float) -> None:
        pass

    # Status
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="orderstatus"),
        default=OrderStatus.RECEIVED,
        server_default=OrderStatus.RECEIVED.value,
        nullable=False,
        index=True,
        doc="Current workflow status of the order"
    )

    # Remarks
    customer_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Special instructions or notes provided by the customer"
    )

    internal_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Internal remarks for lab designers, printers, or staff"
    )

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        doc="Soft delete flag"
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when the order was soft-deleted"
    )

    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
        doc="Optimistic locking version number"
    )

    # System timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Timestamp when the order record was created"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Timestamp when the order record was last updated"
    )

    # SQLAlchemy mapper configuration for optimistic locking
    __mapper_args__ = {
        "version_id_col": version
    }

    # Relationship Back-Reference
    # lazy="selectin" handles async loading of relationships cleanly
    photographer: Mapped["Photographer"] = relationship(
        "Photographer",
        back_populates="orders"
    )

    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem",
        primaryjoin="and_(Order.id==OrderItem.order_id, OrderItem.is_deleted==False)",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    payments: Mapped[list[Payment]] = relationship(
        "Payment",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    invoice: Mapped[Invoice | None] = relationship(
        "Invoice",
        back_populates="order",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    delivery: Mapped[Delivery | None] = relationship(
        "Delivery",
        back_populates="order",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    notifications: Mapped[list[NotificationLog]] = relationship(
        "NotificationLog",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
