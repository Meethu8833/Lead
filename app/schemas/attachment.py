"""
app/schemas/attachment.py

This file defines the Pydantic schemas for the Attachment entity.
Under Clean Architecture, schemas validate request and response formats.
"""

import uuid
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class AttachmentBase(BaseModel):
    entity_name: str = Field(..., description="Target entity class name (Order, OrderItem, Invoice, Delivery)", min_length=1, max_length=100)
    entity_id: uuid.UUID = Field(..., description="UUID of the target entity")
    file_name: str = Field(..., description="Original name of the file", min_length=1, max_length=255)
    mime_type: str = Field(..., description="MIME type of the file", min_length=1, max_length=100)
    storage_path: str = Field(..., description="Storage location path of the uploaded file", min_length=1, max_length=500)

    @field_validator("entity_name")
    @classmethod
    def validate_entity_name(cls, v: str) -> str:
        name = v.strip()
        allowed = {"Order", "OrderItem", "Invoice", "Delivery"}
        if name not in allowed:
            raise ValueError(f"Entity name must be one of {allowed}.")
        return name

    @field_validator("file_name", "mime_type", "storage_path")
    @classmethod
    def cannot_be_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Field cannot be blank or contain only whitespace.")
        return stripped


class AttachmentCreate(AttachmentBase):
    pass


class AttachmentResponse(AttachmentBase):
    id: uuid.UUID
    uploaded_by: str | None
    uploaded_at: datetime

    class Config:
        from_attributes = True
