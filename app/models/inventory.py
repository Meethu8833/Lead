"""
app/models/inventory.py

This file defines the SQLAlchemy database models for the Inventory module.
Under Clean Architecture, this file belongs to the Enterprise Domain Model layer.
"""

import enum
import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Text, Enum, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.database import Base


class InventoryTransactionType(str, enum.Enum):
    """
    Enum representing types of inventory transactions.
    """
    IN = "IN"
    OUT = "OUT"
    ADJUSTMENT = "ADJUSTMENT"


class InventoryItem(Base):
    """
    InventoryItem database model.
    Represents a raw material or physical product tracked in the inventory catalog.
    """
    __tablename__ = "inventory_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier for the inventory item (UUIDv4)"
    )

    name: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        doc="Name of the inventory item (e.g. Matte Roll, Photo Paper)"
    )

    sku: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
        doc="Stock Keeping Unit (SKU) identifier"
    )

    unit: Mapped[str] = mapped_column(
        String(50),
        default="piece",
        nullable=False,
        doc="Measurement unit (e.g. piece, roll, pack)"
    )

    minimum_stock: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Minimum stock threshold below which alerts are triggered"
    )

    current_stock: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Current quantity of items in stock"
    )

    supplier: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Supplier details for replenishing stock"
    )

    remarks: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Internal remarks or specification notes"
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
        doc="Timestamp when the item was soft-deleted"
    )

    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
        doc="Optimistic locking version number"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Timestamp of creation"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Timestamp of last update"
    )

    __mapper_args__ = {
        "version_id_col": version
    }

    # Relationships
    transactions: Mapped[list["InventoryTransaction"]] = relationship(
        "InventoryTransaction",
        back_populates="item",
        cascade="all, delete-orphan"
    )


class InventoryTransaction(Base):
    """
    InventoryTransaction database model.
    Logs every change in stock levels.
    """
    __tablename__ = "inventory_transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier for the transaction (UUIDv4)"
    )

    inventory_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inventory_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Reference to the associated inventory item"
    )

    transaction_type: Mapped[InventoryTransactionType] = mapped_column(
        Enum(InventoryTransactionType, name="inventorytransactiontype"),
        nullable=False,
        doc="Type of stock movement (IN, OUT, ADJUSTMENT)"
    )

    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        doc="Quantity moved (positive only)"
    )

    reason: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Reason for the stock change"
    )

    performed_by: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="User who logged the transaction"
    )

    performed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Timestamp of the transaction"
    )

    # Relationships
    item: Mapped["InventoryItem"] = relationship(
        "InventoryItem",
        back_populates="transactions"
    )
