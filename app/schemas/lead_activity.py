"""
app/schemas/lead_activity.py

This file defines the Pydantic schemas for the Lead Activity & Notes module.
Under Clean Architecture, schemas act as Data Transfer Objects (DTOs) in the Interface
Adapters layer. They validate client inputs (request payloads) and structure client
outputs (response payloads).

Note there is no `LeadActivityCreate`: activities are emitted by the service layer as a
side effect of real domain events, never posted directly by a client. Exposing a create
schema would let a caller fabricate timeline history.
"""

import uuid
from datetime import datetime
from typing import Any, List
from pydantic import BaseModel, Field, field_validator, ConfigDict
from app.models.lead_activity import ActivityType


# =====================================================================
# LEAD NOTES
# =====================================================================

class LeadNoteBase(BaseModel):
    """
    Base Pydantic schema for LeadNote shared fields.
    """
    note: str = Field(..., description="The free-text body of the note", min_length=1, max_length=10000)

    @field_validator("note")
    @classmethod
    def note_cannot_be_blank(cls, v: str) -> str:
        """
        Validates the note body is not just whitespace, and normalizes it by stripping.
        """
        stripped = v.strip()
        if not stripped:
            raise ValueError("Note cannot be empty or contain only whitespace.")
        return stripped


class LeadNoteCreate(LeadNoteBase):
    """
    Schema for validating requests to create a note on a lead.
    `lead_id` is taken from the URL path, not the body, so it is intentionally absent here.
    """
    pass


class LeadNoteUpdate(BaseModel):
    """
    Schema for validating requests to edit an existing note.
    """
    note: str = Field(..., description="The updated free-text body of the note", min_length=1, max_length=10000)

    @field_validator("note")
    @classmethod
    def note_cannot_be_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Note cannot be empty or contain only whitespace.")
        return stripped


class LeadNoteResponse(BaseModel):
    """
    Schema for serializing a LeadNote database record into an API response.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    note: str
    created_by_employee_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class LeadNoteListResponse(BaseModel):
    """
    Schema for a paginated list of notes belonging to a lead.
    """
    items: List[LeadNoteResponse]
    total: int = Field(..., description="Total notes on this lead (ignoring skip/limit)")
    skip: int
    limit: int


# =====================================================================
# LEAD ACTIVITIES
# =====================================================================

class LeadActivityResponse(BaseModel):
    """
    Schema for serializing a LeadActivity database record into an API response.

    The model attribute is `activity_metadata` (renamed to dodge SQLAlchemy's reserved
    `metadata`), but the wire contract is `metadata`. `validation_alias` lets
    `model_validate(orm_obj)` read `activity_metadata` off the ORM object, while
    `serialization_alias` emits it as `metadata` in the JSON response.
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    activity_type: ActivityType
    title: str
    description: str | None
    created_by_employee_id: uuid.UUID | None
    activity_metadata: dict[str, Any] | None = Field(
        None,
        validation_alias="activity_metadata",
        serialization_alias="metadata",
        description="Structured machine-readable payload for the activity",
    )
    created_at: datetime


class LeadActivityListResponse(BaseModel):
    """
    Schema for a paginated timeline of activities belonging to a lead.
    Ordered newest first by the service layer.
    """
    items: List[LeadActivityResponse]
    total: int = Field(..., description="Total activities on this lead (ignoring skip/limit)")
    skip: int
    limit: int
