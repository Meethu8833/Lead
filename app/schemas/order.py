"""
app/schemas/order.py

This file defines the Pydantic schemas for the Order entity.
Under Clean Architecture, schemas act as Data Transfer Objects (DTOs) in the Interface Adapters layer.
They validate client inputs (request payloads) and structure client outputs (response payloads).
"""

import uuid
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator
from app.models.order import OrderStatus
from app.schemas.order_item import OrderItemResponse


class OrderBase(BaseModel):
    """
    Base Pydantic schema for Order shared fields.
    """
    photographer_id: uuid.UUID = Field(..., description="UUID of the photographer placing this order")
    job_name: str = Field(..., description="Descriptive name of the photography job", min_length=1)
    event_type: str | None = Field(None, description="Type of event (e.g. Wedding, Birthday)")
    
    # Dates
    booking_date: datetime = Field(..., description="Date when the order was booked")
    event_date: datetime | None = Field(None, description="Date of the event")
    expected_delivery_date: datetime | None = Field(None, description="Target delivery date")
    
    # Financial
    total_amount: float = Field(0.00, description="Total cost of the order")
    advance_paid: float = Field(0.00, description="Advance payment made")
    
    # Status & Remarks
    status: OrderStatus = Field(OrderStatus.RECEIVED, description="Workflow status of the order")
    customer_notes: str | None = Field(None, description="Special customer requirements")
    internal_notes: str | None = Field(None, description="Internal laboratory staff instructions")

    @field_validator("job_name")
    @classmethod
    def cannot_be_blank(cls, v: str) -> str:
        """
        Validates that job name is not empty or containing only whitespace.
        """
        stripped = v.strip()
        if not stripped:
            raise ValueError("job_name cannot be empty or contain only whitespace.")
        return stripped



    @field_validator("total_amount", "advance_paid")
    @classmethod
    def validate_amounts(cls, v: float) -> float:
        """
        Validates monetary amounts are non-negative.
        """
        if v < 0.0:
            raise ValueError("Amount cannot be negative.")
        return round(v, 2)

    @model_validator(mode="after")
    def validate_financials_and_dates(self) -> "OrderBase":
        """
        Cross-field validation for financials and dates:
        1. expected_delivery_date must be on or after booking_date.
        """
        if self.expected_delivery_date and self.expected_delivery_date < self.booking_date:
            raise ValueError("expected_delivery_date cannot be earlier than booking_date.")

        return self


class OrderCreate(OrderBase):
    """
    Schema for validating requests to create an order.
    Inherits all fields from OrderBase.
    """
    pass


class OrderUpdate(BaseModel):
    """
    Schema for validating requests to update an order.
    All fields are optional to support partial updates.
    """
    photographer_id: uuid.UUID | None = Field(None, description="UUID of the photographer")
    job_name: str | None = Field(None, min_length=1)
    event_type: str | None = Field(None)
    
    booking_date: datetime | None = Field(None)
    event_date: datetime | None = Field(None)
    expected_delivery_date: datetime | None = Field(None)
    
    total_amount: float | None = Field(None)
    advance_paid: float | None = Field(None)
    
    status: OrderStatus | None = Field(None)
    customer_notes: str | None = Field(None)
    internal_notes: str | None = Field(None)
    version: int | None = Field(None, description="Current entity version to enforce optimistic locking")

    @field_validator("job_name")
    @classmethod
    def cannot_be_blank_if_provided(cls, v: str | None) -> str | None:
        """
        Validates job name if provided.
        """
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            raise ValueError("job_name cannot be empty or contain only whitespace.")
        return stripped



    @field_validator("total_amount", "advance_paid")
    @classmethod
    def validate_amounts_if_provided(cls, v: float | None) -> float | None:
        """
        Validates financial values if provided.
        """
        if v is None:
            return v
        if v < 0.0:
            raise ValueError("Amount cannot be negative.")
        return round(v, 2)

    @model_validator(mode="after")
    def validate_financials_and_dates_update(self) -> "OrderUpdate":
        """
        Validates cross-field constraints on updates if values are provided.
        """
        if self.expected_delivery_date is not None and self.booking_date is not None:
            if self.expected_delivery_date < self.booking_date:
                raise ValueError("expected_delivery_date cannot be earlier than booking_date.")

        return self


class OrderResponse(OrderBase):
    """
    Schema for serializing an Order database record into an API response.
    Includes database-assigned values.
    """
    id: uuid.UUID
    order_number: str
    balance_amount: float
    delivered_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemResponse] = []

    class Config:
        from_attributes = True
