"""
app/schemas/photographer.py

This file defines the Pydantic schemas for the Photographer entity.
Under Clean Architecture, schemas act as Data Transfer Objects (DTOs) in the Interface Adapters layer.
They validate client inputs (request payloads) and structure client outputs (response payloads).
"""

import uuid
from datetime import datetime
import re
from pydantic import BaseModel, Field, field_validator
from app.models.photographer import LeadStatus, LeadPriority, ContactMethod


class PhotographerBase(BaseModel):
    """
    Base Pydantic schema for Photographer shared fields.
    """
    name: str = Field(..., description="Full name of the photographer", min_length=1)
    studio_name: str = Field(..., description="Name of the photography studio", min_length=1)
    phone: str = Field(..., description="Unique contact phone number", min_length=1)
    email: str | None = Field(None, description="Contact email address (optional)")
    city: str = Field(..., description="City of operation", min_length=1)
    address: str | None = Field(None, description="Studio physical address (optional)")
    category: str = Field(..., description="Photography category (e.g., Wedding, Portrait, Landscape)", min_length=1)

    # CRM fields
    lead_source: str | None = Field(None, description="Source of the lead (e.g. Google, Instagram)")
    lead_status: LeadStatus = Field(LeadStatus.NEW, description="Lead lifecycle status")
    priority: LeadPriority | None = Field(LeadPriority.MEDIUM, description="Lead priority level")
    assigned_to: uuid.UUID | None = Field(None, description="Assigned employee UUID")
    
    last_contacted_at: datetime | None = Field(None, description="Timestamp of the last contact")
    next_followup_at: datetime | None = Field(None, description="Timestamp for the next follow-up")
    last_contact_method: ContactMethod | None = Field(None, description="Last contact method used")
    last_contact_note: str | None = Field(None, description="Summary note of the last contact")
    
    instagram: str | None = Field(None, description="Instagram username")
    facebook: str | None = Field(None, description="Facebook profile URL")
    website: str | None = Field(None, description="Website URL")
    
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")
    internal_notes: str | None = Field(None, description="Internal CRM notes")
    customer_since: datetime | None = Field(None, description="Timestamp when they became a customer")

    @field_validator("name", "studio_name", "phone", "city", "category")
    @classmethod
    def cannot_be_blank(cls, v: str) -> str:
        """
        Validates that required strings are not just empty spaces.
        """
        stripped = v.strip()
        if not stripped:
            raise ValueError("Field cannot be empty or contain only whitespace.")
        return stripped

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str | None) -> str | None:
        """
        Validates email format using basic regex.
        """
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
        if not re.match(email_regex, v):
            raise ValueError("Invalid email format.")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone_format(cls, v: str) -> str:
        """
        Validates phone format: only digits, +, -, (), and spaces. Must have at least 7 digits.
        """
        v = v.strip()
        if not re.match(r"^\+?[\d\s\-\(\)]+$", v):
            raise ValueError("Phone number contains invalid characters. Only digits, +, -, (), and spaces are allowed.")
        digit_count = sum(1 for c in v if c.isdigit())
        if digit_count < 7:
            raise ValueError("Phone number must contain at least 7 digits.")
        return v

    @field_validator("website", "facebook")
    @classmethod
    def validate_urls(cls, v: str | None) -> str | None:
        """
        Validates web and social profile links start with http:// or https://.
        """
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        url_regex = r"^https?://[^\s/$.?#].[^\s]*$"
        if not re.match(url_regex, v, re.IGNORECASE):
            raise ValueError("Invalid URL format. Must start with http:// or https://")
        return v

    @field_validator("instagram")
    @classmethod
    def validate_instagram_handle(cls, v: str | None) -> str | None:
        """
        Validates instagram handle conforms to Instagram username rules.
        """
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        if v.startswith("@"):
            v = v[1:]
        if not re.match(r"^[a-zA-Z0-9_\.]{1,30}$", v):
            raise ValueError("Invalid Instagram username. Must be 1-30 characters with allowed characters only.")
        return v


class PhotographerCreate(PhotographerBase):
    """
    Schema for validating requests to create a photographer.
    Requires all base fields.
    """
    pass


class PhotographerUpdate(BaseModel):
    """
    Schema for validating requests to update a photographer.
    All fields are optional to allow partial updates.
    """
    name: str | None = Field(None, min_length=1)
    studio_name: str | None = Field(None, min_length=1)
    phone: str | None = Field(None, min_length=1)
    email: str | None = Field(None)
    city: str | None = Field(None, min_length=1)
    address: str | None = Field(None)
    category: str | None = Field(None, min_length=1)
    is_active: bool | None = Field(None, description="Status indicating whether the photographer is active")

    # CRM fields
    lead_source: str | None = Field(None)
    lead_status: LeadStatus | None = Field(None)
    priority: LeadPriority | None = Field(None)
    assigned_to: uuid.UUID | None = Field(None)
    
    last_contacted_at: datetime | None = Field(None)
    next_followup_at: datetime | None = Field(None)
    last_contact_method: ContactMethod | None = Field(None)
    last_contact_note: str | None = Field(None)
    
    instagram: str | None = Field(None)
    facebook: str | None = Field(None)
    website: str | None = Field(None)
    
    tags: list[str] | None = Field(None)
    internal_notes: str | None = Field(None)
    customer_since: datetime | None = Field(None)
    version: int | None = Field(None, description="Current entity version to enforce optimistic locking")

    @field_validator("name", "studio_name", "phone", "city", "category")
    @classmethod
    def cannot_be_blank_if_provided(cls, v: str | None) -> str | None:
        """
        Validates that fields are not empty if they are passed.
        """
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            raise ValueError("Field cannot be empty or contain only whitespace.")
        return stripped

    @field_validator("email")
    @classmethod
    def validate_email_format_if_provided(cls, v: str | None) -> str | None:
        """
        Validates email format if it is provided.
        """
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
        if not re.match(email_regex, v):
            raise ValueError("Invalid email format.")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone_format_if_provided(cls, v: str | None) -> str | None:
        """
        Validates phone format if provided.
        """
        if v is None:
            return v
        v = v.strip()
        if not re.match(r"^\+?[\d\s\-\(\)]+$", v):
            raise ValueError("Phone number contains invalid characters.")
        digit_count = sum(1 for c in v if c.isdigit())
        if digit_count < 7:
            raise ValueError("Phone number must contain at least 7 digits.")
        return v

    @field_validator("website", "facebook")
    @classmethod
    def validate_urls_if_provided(cls, v: str | None) -> str | None:
        """
        Validates URL fields if provided.
        """
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        url_regex = r"^https?://[^\s/$.?#].[^\s]*$"
        if not re.match(url_regex, v, re.IGNORECASE):
            raise ValueError("Invalid URL format. Must start with http:// or https://")
        return v

    @field_validator("instagram")
    @classmethod
    def validate_instagram_handle_if_provided(cls, v: str | None) -> str | None:
        """
        Validates instagram username if provided.
        """
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        if v.startswith("@"):
            v = v[1:]
        if not re.match(r"^[a-zA-Z0-9_\.]{1,30}$", v):
            raise ValueError("Invalid Instagram username.")
        return v


class PhotographerResponse(PhotographerBase):
    """
    Schema for serializing a Photographer database record into an API response.
    Includes database-assigned values (id, is_active, created_at, updated_at).
    """
    id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        # Pydantic v2 attribute parsing (equivalent to orm_mode = True in Pydantic v1)
        from_attributes = True

