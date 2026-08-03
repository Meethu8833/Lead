"""
app/models/delivery.py

SQLAlchemy model for Delivery.
"""

from __future__ import annotations
import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, DateTime, Enum, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.order import Order


class DeliveryMethod(str, enum.Enum):
    PICKUP = "PICKUP"
    COURIER = "COURIER"
    HOME_DELIVERY = "HOME_DELIVERY"
    STORE = "STORE"


class DeliveryStatus(str, enum.Enum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    IN_TRANSIT = "IN_TRANSIT"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    RETURNED = "RETURNED"


class Delivery(Base):
    __tablename__ = "deliveries"

    __table_args__ = (
        CheckConstraint(
            "dispatch_date IS NULL OR delivered_date IS NULL OR dispatch_date <= delivered_date",
            name="chk_delivery_dates_logical"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier for the delivery (UUIDv4)"
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        doc="Reference to the order this delivery belongs to"
    )

    delivery_method: Mapped[DeliveryMethod] = mapped_column(
        Enum(DeliveryMethod, name="deliverymethod"),
        nullable=False,
        doc="Method used for delivery (PICKUP, COURIER, etc.)"
    )

    dispatch_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp representing when the delivery was dispatched"
    )

    expected_delivery: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        doc="Timestamp representing when the delivery is expected to arrive"
    )

    delivered_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp representing when the delivery was successfully delivered"
    )

    tracking_number: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        doc="Courier tracking number"
    )

    courier_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        doc="Name of the courier service or carrier"
    )

    remarks: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Additional notes about delivery (e.g., instructions)"
    )

    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, name="deliverystatus"),
        default=DeliveryStatus.PENDING,
        server_default=DeliveryStatus.PENDING.value,
        nullable=False,
        doc="Current status of the delivery"
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
        back_populates="delivery"
    )
