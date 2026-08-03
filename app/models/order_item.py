"""
app/models/order_item.py

This file defines the SQLAlchemy database model for the OrderItem entity.
Under Clean Architecture, this file belongs to the Enterprise Domain Model layer.
It represents the persistent structure of an item within an order in PostgreSQL.
"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Integer, Numeric, DateTime, Text, ForeignKey, Enum as SQLEnum, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.order import Order
    from app.models.product import Product


class ProductionStage(str, enum.Enum):
    """
    Enum representing the production stages of a Colour Lab order item.
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


class OrderItem(Base):
    """
    OrderItem database model.
    Represents an individual item line in a photographer's order.
    
    Snapshot Fields:
    - product_name and product_category store the historical product identity.
    - unit_price stores the transaction-time price of the product.
    This preserves the order's financial integrity even if the catalog is updated or products are deleted.
    """
    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier for the order item (UUIDv4)"
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Reference to the parent order"
    )

    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Reference to the catalog product"
    )

    # Snapshot Fields (Historical Data Preservation)
    product_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Snapshot of the product name at purchase time"
    )

    product_category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="Snapshot of the product category at purchase time"
    )

    # Pricing SNAPSHOT
    unit_price: Mapped[float] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        doc="Snapshot of unit price at purchase time"
    )

    quantity: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
        doc="Quantity of this product ordered"
    )

    discount: Mapped[float] = mapped_column(
        Numeric(10, 2),
        default=0.00,
        nullable=False,
        doc="Monetary discount applied to this item line"
    )

    subtotal: Mapped[float] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        doc="Calculated line subtotal: (unit_price * quantity) - discount"
    )

    # Configuration SNAPSHOT
    album_size: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        doc="Album size dimension snapshots (if applicable)"
    )

    sheet_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        doc="Album paper sheet type snapshots (if applicable)"
    )

    cover_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        doc="Album cover type snapshots (if applicable)"
    )

    remarks: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Item-specific notes or customer remarks"
    )

    production_stage: Mapped[ProductionStage] = mapped_column(
        SQLEnum(ProductionStage, name="productionstage"),
        default=ProductionStage.RECEIVED,
        server_default=ProductionStage.RECEIVED.value,
        nullable=False,
        index=True,
        doc="Current production stage of this order item"
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when production started"
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when production completed"
    )

    assigned_employee: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        doc="UUID of the employee assigned to this stage"
    )

    production_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Notes relating to production/workflow status"
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
        doc="Timestamp when the order item was soft-deleted"
    )

    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
        doc="Optimistic locking version number"
    )

    # System Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Timestamp when the item line was created"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Timestamp when the item line was last updated"
    )

    # SQLAlchemy mapper configuration for optimistic locking
    __mapper_args__ = {
        "version_id_col": version
    }

    # Relationships
    order: Mapped["Order"] = relationship(
        "Order",
        back_populates="items"
    )

    product: Mapped["Product | None"] = relationship(
        "Product",
        back_populates="order_items"
    )
