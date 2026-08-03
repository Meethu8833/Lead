"""
app/schemas/lead.py

This file defines the Pydantic schemas for the Lead entity.
Under Clean Architecture, schemas act as Data Transfer Objects (DTOs) in the Interface Adapters layer.
They validate client inputs (request payloads) and structure client outputs (response payloads).
"""

import uuid
from datetime import datetime
import re
from typing import List
from pydantic import BaseModel, Field, field_validator
from app.models.lead import LeadStatus, LeadSource


class LeadBase(BaseModel):
    """
    Base Pydantic schema for Lead shared fields.
    """
    business_name: str = Field(..., description="Name of the prospective photography business/studio", min_length=1)
    contact_person: str | None = Field(None, description="Primary contact person at the business")
    phone: str = Field(..., description="Unique contact phone number", min_length=1)
    whatsapp: str | None = Field(None, description="WhatsApp contact number (optional)")
    email: str | None = Field(None, description="Contact email address (optional)")
    instagram: str | None = Field(None, description="Instagram username")
    facebook: str | None = Field(None, description="Facebook profile/page URL")
    website: str | None = Field(None, description="Website URL")
    address: str | None = Field(None, description="Full street address")
    city: str | None = Field(None, description="City of operation")
    district: str | None = Field(None, description="District of operation")
    state: str | None = Field(None, description="State/province of operation")
    country: str | None = Field(None, description="Country of operation")
    latitude: float | None = Field(None, ge=-90, le=90, description="Geographic latitude")
    longitude: float | None = Field(None, ge=-180, le=180, description="Geographic longitude")
    source: LeadSource = Field(LeadSource.MANUAL, description="Origin channel of the lead")
    status: LeadStatus = Field(LeadStatus.NEW, description="CRM lifecycle status")
    assigned_employee_id: uuid.UUID | None = Field(None, description="Employee UUID assigned to this lead")
    remarks: str | None = Field(None, description="Free-form remarks/notes")

    @field_validator("business_name")
    @classmethod
    def cannot_be_blank(cls, v: str) -> str:
        """
        Validates that required strings are not just empty spaces.
        """
        stripped = v.strip()
        if not stripped:
            raise ValueError("Field cannot be empty or contain only whitespace.")
        return stripped

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

    @field_validator("whatsapp")
    @classmethod
    def validate_whatsapp_format(cls, v: str | None) -> str | None:
        """
        Validates WhatsApp number format if provided.
        """
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        if not re.match(r"^\+?[\d\s\-\(\)]+$", v):
            raise ValueError("WhatsApp number contains invalid characters. Only digits, +, -, (), and spaces are allowed.")
        digit_count = sum(1 for c in v if c.isdigit())
        if digit_count < 7:
            raise ValueError("WhatsApp number must contain at least 7 digits.")
        return v

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


class LeadCreate(LeadBase):
    """
    Schema for validating requests to create a lead.
    Requires all base fields (business_name and phone are mandatory; the rest are optional).
    """
    pass


class LeadUpdate(BaseModel):
    """
    Schema for validating requests to update a lead.
    All fields are optional to allow partial updates.
    """
    business_name: str | None = Field(None, min_length=1)
    contact_person: str | None = Field(None)
    phone: str | None = Field(None, min_length=1)
    whatsapp: str | None = Field(None)
    email: str | None = Field(None)
    instagram: str | None = Field(None)
    facebook: str | None = Field(None)
    website: str | None = Field(None)
    address: str | None = Field(None)
    city: str | None = Field(None)
    district: str | None = Field(None)
    state: str | None = Field(None)
    country: str | None = Field(None)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    source: LeadSource | None = Field(None)
    status: LeadStatus | None = Field(None)
    assigned_employee_id: uuid.UUID | None = Field(None)
    remarks: str | None = Field(None)
    is_converted: bool | None = Field(None, description="Whether the lead has converted into a customer")
    version: int | None = Field(None, description="Current entity version to enforce optimistic locking")

    @field_validator("business_name")
    @classmethod
    def cannot_be_blank_if_provided(cls, v: str | None) -> str | None:
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            raise ValueError("Field cannot be empty or contain only whitespace.")
        return stripped

    @field_validator("phone")
    @classmethod
    def validate_phone_format_if_provided(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not re.match(r"^\+?[\d\s\-\(\)]+$", v):
            raise ValueError("Phone number contains invalid characters.")
        digit_count = sum(1 for c in v if c.isdigit())
        if digit_count < 7:
            raise ValueError("Phone number must contain at least 7 digits.")
        return v

    @field_validator("whatsapp")
    @classmethod
    def validate_whatsapp_format_if_provided(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        if not re.match(r"^\+?[\d\s\-\(\)]+$", v):
            raise ValueError("WhatsApp number contains invalid characters.")
        digit_count = sum(1 for c in v if c.isdigit())
        if digit_count < 7:
            raise ValueError("WhatsApp number must contain at least 7 digits.")
        return v

    @field_validator("email")
    @classmethod
    def validate_email_format_if_provided(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
        if not re.match(email_regex, v):
            raise ValueError("Invalid email format.")
        return v

    @field_validator("website", "facebook")
    @classmethod
    def validate_urls_if_provided(cls, v: str | None) -> str | None:
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


class LeadResponse(LeadBase):
    """
    Schema for serializing a Lead database record into an API response.
    """
    id: uuid.UUID
    is_converted: bool
    version: int
    created_at: datetime
    updated_at: datetime

    class Config:
        # Pydantic v2 attribute parsing (equivalent to orm_mode = True in Pydantic v1)
        from_attributes = True


class LeadListResponse(BaseModel):
    """
    Schema for a paginated list of leads.
    """
    items: List[LeadResponse]
    total: int = Field(..., description="Total number of leads matching the query (ignoring skip/limit)")
    skip: int
    limit: int
