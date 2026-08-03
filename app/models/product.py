"""
app/models/product.py

This file defines the SQLAlchemy database model for the Product entity (Product Catalog).
Under Clean Architecture, this file belongs to the Enterprise Domain Model layer.
It represents the persistent structure of a product in PostgreSQL.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Boolean, DateTime, Text, Numeric, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.order_item import OrderItem


class Product(Base):
    """
    Product database model.
    Represents the database structure of a reusable product in the Product Catalog.

    Business Rules:
    - Product names must be unique.
    - is_active flags if the product can be selected for new order items.
    """
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier for the product (UUIDv4)"
    )

    name: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        doc="Unique name of the product (e.g., Wedding Album, Parent Album)"
    )

    category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        doc="Category of the product (e.g., Album, Frame, Print)"
    )

    size: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        doc="Size dimensions or specification of the product (e.g., 12x18, 12x36, 10x12)"
    )

    unit: Mapped[str] = mapped_column(
        String(50),
        default="piece",
        nullable=False,
        doc="Measurement unit of the product (e.g., piece, page, sheet)"
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Detailed description of the product specification"
    )

    base_price: Mapped[float] = mapped_column(
        Numeric(10, 2),
        default=0.00,
        nullable=False,
        doc="Base price of the product for pricing calculations"
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        doc="Indicates if the product is active and selectable for new orders"
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
        doc="Timestamp when the product was soft-deleted"
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
        doc="Timestamp when the product was created"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Timestamp when the product was last updated"
    )

    # SQLAlchemy mapper configuration for optimistic locking
    __mapper_args__ = {
        "version_id_col": version
    }

    # Relationships
    order_items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem",
        back_populates="product"
    )
