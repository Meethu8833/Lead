"""
app/models/invoice.py

SQLAlchemy model for Invoice.
"""

from __future__ import annotations
import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Numeric, DateTime, Enum, ForeignKey, CheckConstraint, Index, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.order import Order


class InvoiceStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    GENERATED = "GENERATED"
    SENT = "SENT"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class Invoice(Base):
    __tablename__ = "invoices"

    __table_args__ = (
        CheckConstraint("discount >= 0", name="chk_invoice_discount_non_negative"),
        CheckConstraint("gst_percentage >= 0 AND gst_percentage <= 100", name="chk_invoice_gst_percentage_valid"),
        CheckConstraint("grand_total >= 0", name="chk_invoice_grand_total_non_negative"),
        CheckConstraint("paid_amount >= 0", name="chk_invoice_paid_amount_non_negative"),
        Index(
            "idx_active_invoice_per_order",
            "order_id",
            unique=True,
            postgresql_where=text("status != 'CANCELLED'")
        )
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier for the invoice (UUIDv4)"
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        doc="Reference to the order this invoice belongs to"
    )

    invoice_number: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        doc="Unique automatically generated invoice number (e.g. INV-2026-000001)"
    )

    invoice_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Date when the invoice was generated"
    )

    subtotal: Mapped[float] = mapped_column(
        Numeric(10, 2),
        default=0.00,
        nullable=False,
        doc="Total price before discount and taxes"
    )

    discount: Mapped[float] = mapped_column(
        Numeric(10, 2),
        default=0.00,
        nullable=False,
        doc="Discount amount applied to the invoice"
    )

    gst_percentage: Mapped[float] = mapped_column(
        Numeric(5, 2),
        default=18.00,
        nullable=False,
        doc="GST percentage (e.g. 18.00%)"
    )

    gst_amount: Mapped[float] = mapped_column(
        Numeric(10, 2),
        default=0.00,
        nullable=False,
        doc="Calculated GST tax amount"
    )

    grand_total: Mapped[float] = mapped_column(
        Numeric(10, 2),
        default=0.00,
        nullable=False,
        doc="Final total amount after discount and GST"
    )

    paid_amount: Mapped[float] = mapped_column(
        Numeric(10, 2),
        default=0.00,
        nullable=False,
        doc="Snapshot of paid amount at invoice generation/recalculation"
    )

    balance_amount: Mapped[float] = mapped_column(
        Numeric(10, 2),
        default=0.00,
        nullable=False,
        doc="Snapshot of remaining balance amount (grand_total - paid_amount)"
    )

    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(InvoiceStatus, name="invoicestatus"),
        default=InvoiceStatus.DRAFT,
        server_default=InvoiceStatus.DRAFT.value,
        nullable=False,
        doc="Current status of the invoice"
    )

    pdf_path: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="File path to the generated PDF copy of the invoice"
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
        back_populates="invoice"
    )
