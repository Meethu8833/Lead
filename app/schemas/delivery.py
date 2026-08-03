"""
app/schemas/delivery.py

Pydantic schemas for Delivery.
"""

import uuid
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator
from app.models.delivery import DeliveryMethod, DeliveryStatus


class DeliveryBase(BaseModel):
    delivery_method: DeliveryMethod = Field(..., description="Method of delivery")
    dispatch_date: datetime | None = Field(None, description="Dispatched timestamp")
    expected_delivery: datetime | None = Field(None, description="Expected delivery timestamp")
    tracking_number: str | None = Field(None, description="Courier tracking number")
    courier_name: str | None = Field(None, description="Name of the courier service")
    remarks: str | None = Field(None, description="Additional delivery remarks")
    status: DeliveryStatus = Field(DeliveryStatus.PENDING, description="Current delivery status")

    @field_validator("tracking_number", "courier_name")
    @classmethod
    def strip_whitespace(cls, v: str | None) -> str | None:
        if v is not None:
            stripped = v.strip()
            if not stripped:
                return None
            return stripped
        return v

    @model_validator(mode="after")
    def validate_dates(self) -> "DeliveryBase":
        if self.dispatch_date and self.expected_delivery:
            if self.expected_delivery < self.dispatch_date:
                raise ValueError("expected_delivery date cannot be earlier than dispatch_date.")
        return self


class DeliveryCreate(DeliveryBase):
    pass


class DeliveryUpdate(BaseModel):
    delivery_method: DeliveryMethod | None = Field(None)
    dispatch_date: datetime | None = Field(None)
    expected_delivery: datetime | None = Field(None)
    delivered_date: datetime | None = Field(None)
    tracking_number: str | None = Field(None)
    courier_name: str | None = Field(None)
    remarks: str | None = Field(None)
    status: DeliveryStatus | None = Field(None)

    @field_validator("tracking_number", "courier_name")
    @classmethod
    def strip_whitespace_if_provided(cls, v: str | None) -> str | None:
        if v is not None:
            stripped = v.strip()
            if not stripped:
                return None
            return stripped
        return v


class DeliveryResponse(DeliveryBase):
    id: uuid.UUID
    order_id: uuid.UUID
    delivered_date: datetime | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
