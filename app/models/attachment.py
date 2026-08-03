"""
app/models/attachment.py

This file defines the SQLAlchemy database model for the Attachment entity.
Under Clean Architecture, this resides in the Enterprise Domain Model layer.
"""

import uuid
from datetime import datetime
from sqlalchemy import String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.core.database import Base


class Attachment(Base):
    """
    Attachment database model.
    Represents metadata about files attached to business entities (Orders, OrderItems, Invoices, Deliveries).
    """
    __tablename__ = "attachments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier for the attachment (UUIDv4)"
    )

    entity_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        doc="Name of the audited model/entity class (Order, OrderItem, Invoice, Delivery)"
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        doc="ID of the associated entity record"
    )

    file_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Original filename uploaded"
    )

    mime_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="MIME type of the file (e.g. image/png, application/pdf)"
    )

    storage_path: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        doc="Path where the file is stored in storage"
    )

    uploaded_by: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="User identifier who uploaded the file"
    )

    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Timestamp of file upload"
    )
