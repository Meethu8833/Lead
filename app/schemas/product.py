"""
app/schemas/product.py

This file defines the Pydantic schemas for the Product entity.
Under Clean Architecture, schemas act as Data Transfer Objects (DTOs) in the Interface Adapters layer.
They validate client inputs (request payloads) and structure client outputs (response payloads).
"""

import uuid
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class ProductBase(BaseModel):
    """
    Base Pydantic schema for Product shared fields.
    """
    name: str = Field(..., description="Unique name of the product", min_length=1, max_length=255)
    category: str = Field(..., description="Category of the product (e.g. Album, Frame, Print)", min_length=1, max_length=100)
    size: str | None = Field(None, description="Size dimensions or specification of the product", max_length=50)
    unit: str = Field("piece", description="Measurement unit of the product (e.g. piece, sheet)", max_length=50)
    description: str | None = Field(None, description="Detailed product description")
    base_price: float = Field(0.00, description="Base price of the product")
    is_active: bool = Field(True, description="Indicates if the product is active and selectable")

    @field_validator("name", "category")
    @classmethod
    def cannot_be_blank(cls, v: str) -> str:
        """
        Validates that string fields are not blank or containing only whitespace.
        """
        stripped = v.strip()
        if not stripped:
            raise ValueError("Field cannot be empty or contain only whitespace.")
        return stripped

    @field_validator("base_price")
    @classmethod
    def validate_base_price(cls, v: float) -> float:
        """
        Validates base price is non-negative.
        """
        if v < 0.0:
            raise ValueError("base_price cannot be negative.")
        return round(v, 2)


class ProductCreate(ProductBase):
    """
    Schema for validating requests to create a Product.
    """
    pass


class ProductUpdate(BaseModel):
    """
    Schema for validating requests to update a Product. All fields optional.
    """
    name: str | None = Field(None, min_length=1, max_length=255)
    category: str | None = Field(None, min_length=1, max_length=100)
    size: str | None = Field(None, max_length=50)
    unit: str | None = Field(None, max_length=50)
    description: str | None = Field(None)
    base_price: float | None = Field(None)
    is_active: bool | None = Field(None)
    version: int | None = Field(None, description="Current entity version to enforce optimistic locking")

    @field_validator("name", "category")
    @classmethod
    def cannot_be_blank_if_provided(cls, v: str | None) -> str | None:
        """
        Validates string fields if provided.
        """
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            raise ValueError("Field cannot be empty or contain only whitespace.")
        return stripped

    @field_validator("base_price")
    @classmethod
    def validate_base_price_if_provided(cls, v: float | None) -> float | None:
        """
        Validates base price if provided.
        """
        if v is None:
            return v
        if v < 0.0:
            raise ValueError("base_price cannot be negative.")
        return round(v, 2)


class ProductResponse(ProductBase):
    """
    Schema for serializing a Product database record into an API response.
    """
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
