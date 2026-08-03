"""
app/schemas/order_item.py

This file defines the Pydantic schemas for the OrderItem entity.
Under Clean Architecture, schemas act as Data Transfer Objects (DTOs) in the Interface Adapters layer.
They validate client inputs (request payloads) and structure client outputs (response payloads).
"""

import uuid
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator
from app.models.order_item import ProductionStage


class OrderItemBase(BaseModel):
    """
    Base Pydantic schema for OrderItem shared fields.
    """
    quantity: int = Field(1, description="Quantity of the product ordered")
    discount: float = Field(0.00, description="Monetary discount applied to this item line")
    album_size: str | None = Field(None, description="Album size specifications", max_length=50)
    sheet_type: str | None = Field(None, description="Album paper sheet type", max_length=100)
    cover_type: str | None = Field(None, description="Album cover type", max_length=100)
    remarks: str | None = Field(None, description="Item-specific notes or remarks")

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: int) -> int:
        """
        Validates quantity is at least 1.
        """
        if v < 1:
            raise ValueError("quantity must be at least 1.")
        return v

    @field_validator("discount")
    @classmethod
    def validate_discount(cls, v: float) -> float:
        """
        Validates discount is non-negative.
        """
        if v < 0.0:
            raise ValueError("discount cannot be negative.")
        return round(v, 2)


class OrderItemCreate(OrderItemBase):
    """
    Schema for validating requests to create an OrderItem.
    """
    product_id: uuid.UUID = Field(..., description="UUID of the product in the catalog")
    unit_price: float | None = Field(None, description="Optional price override. If omitted, uses the product's base price")

    @field_validator("unit_price")
    @classmethod
    def validate_unit_price(cls, v: float | None) -> float | None:
        """
        Validates unit price if provided.
        """
        if v is not None and v < 0.0:
            raise ValueError("unit_price cannot be negative.")
        return round(v, 2) if v is not None else None


class OrderItemUpdate(BaseModel):
    """
    Schema for validating requests to update an OrderItem. All fields optional.
    """
    product_id: uuid.UUID | None = Field(None)
    quantity: int | None = Field(None)
    unit_price: float | None = Field(None)
    discount: float | None = Field(None)
    album_size: str | None = Field(None)
    sheet_type: str | None = Field(None)
    cover_type: str | None = Field(None)
    remarks: str | None = Field(None)
    version: int | None = Field(None, description="Current entity version to enforce optimistic locking")

    @field_validator("quantity")
    @classmethod
    def validate_quantity_if_provided(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v < 1:
            raise ValueError("quantity must be at least 1.")
        return v

    @field_validator("unit_price", "discount")
    @classmethod
    def validate_prices_if_provided(cls, v: float | None) -> float | None:
        if v is None:
            return v
        if v < 0.0:
            raise ValueError("Amount cannot be negative.")
        return round(v, 2)


class OrderItemResponse(OrderItemBase):
    """
    Schema for serializing an OrderItem database record into an API response.
    Includes snapshot and calculated fields.
    """
    id: uuid.UUID
    order_id: uuid.UUID
    product_id: uuid.UUID | None
    product_name: str
    product_category: str
    unit_price: float
    subtotal: float
    production_stage: ProductionStage
    started_at: datetime | None = None
    completed_at: datetime | None = None
    assigned_employee: uuid.UUID | None = None
    production_notes: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @model_validator(mode="after")
    def validate_subtotal_calculation(self) -> "OrderItemResponse":
        """
        Ensures response subtotal matches the expected business rule:
        subtotal = (unit_price * quantity) - discount
        """
        expected_subtotal = round((self.unit_price * self.quantity) - self.discount, 2)
        # Avoid minor floating point differences in check
        if abs(self.subtotal - expected_subtotal) > 0.01:
            raise ValueError(f"Inconsistent subtotal logic. Expected {expected_subtotal}, got {self.subtotal}")
        return self


class ProductionStageUpdate(BaseModel):
    """
    Schema for updating production stage of an OrderItem.
    """
    production_stage: ProductionStage = Field(..., description="Target production stage")
    allow_backward: bool = Field(False, description="Explicit flag to allow transitioning backwards in sequence")
    version: int | None = Field(None, description="Current entity version to enforce optimistic locking")


class EmployeeAssignment(BaseModel):
    """
    Schema for assigning an employee to an OrderItem.
    """
    employee_id: uuid.UUID | None = Field(None, description="UUID of the assigned employee (or null to unassign)")


class ProductionNotesUpdate(BaseModel):
    """
    Schema for updating production notes on an OrderItem.
    """
    production_notes: str | None = Field(None, description="Production-specific internal notes")


class ProductionDashboardResponse(BaseModel):
    """
    Schema for production dashboard statistics.
    """
    items_per_stage: dict[str, int] = Field(..., description="Count of items per production stage")
    items_delayed: int = Field(..., description="Count of items whose orders are past their expected delivery date")
    items_ready: int = Field(..., description="Count of items ready for delivery")
    items_delivered_today: int = Field(..., description="Count of items delivered today")
