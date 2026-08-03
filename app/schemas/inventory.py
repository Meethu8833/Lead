"""
app/schemas/inventory.py

This file defines the Pydantic schemas for the Inventory module.
Under Clean Architecture, they act as DTOs in the Interface Adapters layer.
"""

import uuid
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from app.models.inventory import InventoryTransactionType


class InventoryItemBase(BaseModel):
    name: str = Field(..., description="Unique name of the inventory item", min_length=1, max_length=255)
    sku: str = Field(..., description="Unique SKU code", min_length=1, max_length=100)
    unit: str = Field("piece", description="Measurement unit (e.g. piece, roll, pack)", max_length=50)
    minimum_stock: int = Field(0, description="Minimum safety stock level")
    current_stock: int = Field(0, description="Current stock level")
    supplier: str | None = Field(None, description="Supplier details")
    remarks: str | None = Field(None, description="Additional remarks")

    @field_validator("name", "sku")
    @classmethod
    def cannot_be_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Field cannot be empty or blank.")
        return stripped

    @field_validator("minimum_stock", "current_stock")
    @classmethod
    def validate_stock_levels(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Stock level cannot be negative.")
        return v


class InventoryItemCreate(InventoryItemBase):
    pass


class InventoryItemUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    sku: str | None = Field(None, min_length=1, max_length=100)
    unit: str | None = Field(None, max_length=50)
    minimum_stock: int | None = Field(None)
    current_stock: int | None = Field(None)
    supplier: str | None = Field(None)
    remarks: str | None = Field(None)
    version: int | None = Field(None, description="Version number for optimistic locking verification")

    @field_validator("name", "sku")
    @classmethod
    def cannot_be_blank_if_provided(cls, v: str | None) -> str | None:
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            raise ValueError("Field cannot be empty.")
        return stripped


class InventoryItemResponse(InventoryItemBase):
    id: uuid.UUID
    version: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InventoryTransactionBase(BaseModel):
    inventory_item_id: uuid.UUID = Field(..., description="Reference to the inventory item")
    transaction_type: InventoryTransactionType = Field(..., description="Movement type: IN, OUT, ADJUSTMENT")
    quantity: int = Field(..., description="Quantity moved (positive for IN/OUT, signed for ADJUSTMENT)")
    reason: str = Field(..., description="Reason for transaction", min_length=1, max_length=255)

    from pydantic import model_validator

    @model_validator(mode="after")
    def validate_transaction_quantity(self) -> "InventoryTransactionBase":
        if self.transaction_type in (InventoryTransactionType.IN, InventoryTransactionType.OUT):
            if self.quantity <= 0:
                raise ValueError("Quantity must be strictly greater than 0 for IN/OUT transactions.")
        else:
            if self.quantity == 0:
                raise ValueError("Quantity cannot be 0 for ADJUSTMENT transactions.")
        return self


class InventoryTransactionCreate(InventoryTransactionBase):
    pass


class InventoryTransactionResponse(InventoryTransactionBase):
    id: uuid.UUID
    performed_by: str | None
    performed_at: datetime

    class Config:
        from_attributes = True
