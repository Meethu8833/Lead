"""
app/schemas/payment.py

Pydantic schemas for Payment.
"""

import uuid
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from app.models.payment import PaymentMethod


class PaymentBase(BaseModel):
    payment_method: PaymentMethod = Field(..., description="Payment method used")
    amount: float = Field(..., description="Payment amount received")
    reference_number: str | None = Field(None, description="Transaction ID or payment reference number")
    remarks: str | None = Field(None, description="Optional payment comments/remarks")
    received_at: datetime = Field(default_factory=datetime.utcnow, description="Timestamp when the payment was received")

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: float) -> float:
        if v <= 0.0:
            raise ValueError("Payment amount must be greater than zero.")
        return round(v, 2)

    @field_validator("reference_number")
    @classmethod
    def validate_reference_number(cls, v: str | None) -> str | None:
        if v is not None:
            stripped = v.strip()
            if not stripped:
                return None
            return stripped
        return v


class PaymentCreate(PaymentBase):
    allow_overpayment: bool = Field(False, description="Flag to explicitly bypass overpayment prevention checks")


class PaymentUpdate(BaseModel):
    payment_method: PaymentMethod | None = Field(None)
    amount: float | None = Field(None)
    reference_number: str | None = Field(None)
    remarks: str | None = Field(None)
    received_at: datetime | None = Field(None)

    @field_validator("amount")
    @classmethod
    def validate_amount_if_provided(cls, v: float | None) -> float | None:
        if v is not None:
            if v <= 0.0:
                raise ValueError("Payment amount must be greater than zero.")
            return round(v, 2)
        return v


class PaymentResponse(PaymentBase):
    id: uuid.UUID
    order_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
