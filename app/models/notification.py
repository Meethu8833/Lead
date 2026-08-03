"""
app/models/notification.py

SQLAlchemy model for NotificationLog.
"""

from __future__ import annotations
import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Text, DateTime, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.order import Order


class NotificationType(str, enum.Enum):
    ORDER_CREATED = "ORDER_CREATED"
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED"
    PRODUCTION_READY = "PRODUCTION_READY"
    ORDER_DELIVERED = "ORDER_DELIVERED"
    INVOICE_GENERATED = "INVOICE_GENERATED"
    FOLLOWUP_REMINDER = "FOLLOWUP_REMINDER"


class NotificationChannel(str, enum.Enum):
    SYSTEM = "SYSTEM"
    WHATSAPP = "WHATSAPP"
    EMAIL = "EMAIL"
    SMS = "SMS"


class NotificationStatus(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier for the notification log (UUIDv4)"
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Reference to the order this notification relates to"
    )

    notification_type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, name="notificationtype"),
        nullable=False,
        doc="Type of the notification (e.g., ORDER_CREATED)"
    )

    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, name="notificationchannel"),
        nullable=False,
        doc="Delivery channel used (SYSTEM, WHATSAPP, etc.)"
    )

    recipient: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Target address, phone number, or identifier"
    )

    message_body: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Body content of the notification message"
    )

    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, name="notificationstatus"),
        default=NotificationStatus.PENDING,
        server_default=NotificationStatus.PENDING.value,
        nullable=False,
        doc="Sending status of the notification"
    )

    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp of when the notification was successfully sent"
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
        back_populates="notifications"
    )
