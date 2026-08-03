"""
app/schemas/invoice.py

Pydantic schemas for Invoice.
"""

import uuid
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator
from app.models.invoice import InvoiceStatus


class InvoiceBase(BaseModel):
    subtotal: float = Field(..., description="Invoice subtotal before discount/tax")
    discount: float = Field(0.00, description="Discount amount applied")
    gst_percentage: float = Field(18.00, description="GST percentage (e.g., 18.00)")
    status: InvoiceStatus = Field(InvoiceStatus.DRAFT, description="Current status of the invoice")
    pdf_path: str | None = Field(None, description="Optional path to the invoice PDF file")

    @field_validator("subtotal", "discount", "gst_percentage")
    @classmethod
    def validate_non_negative(cls, v: float) -> float:
        if v < 0.0:
            raise ValueError("Values cannot be negative.")
        return round(v, 2)

    @model_validator(mode="after")
    def validate_discount_limit(self) -> "InvoiceBase":
        if self.discount > self.subtotal:
            raise ValueError("Discount cannot exceed the subtotal.")
        return self


class InvoiceCreate(InvoiceBase):
    pass


class InvoiceUpdate(BaseModel):
    subtotal: float | None = Field(None)
    discount: float | None = Field(None)
    gst_percentage: float | None = Field(None)
    status: InvoiceStatus | None = Field(None)
    pdf_path: str | None = Field(None)

    @field_validator("subtotal", "discount", "gst_percentage")
    @classmethod
    def validate_non_negative_if_provided(cls, v: float | None) -> float | None:
        if v is not None:
            if v < 0.0:
                raise ValueError("Values cannot be negative.")
            return round(v, 2)
        return v


class InvoiceResponse(InvoiceBase):
    id: uuid.UUID
    order_id: uuid.UUID
    invoice_number: str
    invoice_date: datetime
    gst_amount: float
    grand_total: float
    paid_amount: float
    balance_amount: float
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
