"""
app/schemas/follow_up.py

This file defines the Pydantic schemas for the Follow-up & Task Management module.
Under Clean Architecture, schemas act as Data Transfer Objects (DTOs) in the Interface
Adapters layer. They validate client inputs (request payloads) and structure client outputs
(response payloads).

Note the deliberate asymmetry between create/update and the lifecycle transitions:
`FollowUpTaskUpdate` cannot set `status` or `completed_at`. Completing, rescheduling and
cancelling are modelled as their own operations with their own schemas, because each has to
emit a specific timeline activity and enforce its own preconditions. Allowing a generic PUT
to flip `status` to COMPLETED would create a second, silent completion path that writes no
activity — which is exactly the inconsistency this module exists to prevent.
"""

import uuid
from datetime import datetime, timezone
from typing import List
from pydantic import BaseModel, Field, field_validator, ConfigDict

from app.models.follow_up import FollowUpType, FollowUpPriority, FollowUpStatus


def _require_aware(value: datetime, field_name: str) -> datetime:
    """
    Normalizes an incoming datetime to timezone-aware UTC.

    A naive datetime is *assumed* UTC rather than rejected. Clients across this codebase
    submit both forms, and silently comparing a naive value against a timezone-aware column
    raises `TypeError: can't compare offset-naive and offset-aware datetimes` deep inside
    the service. Normalizing once, here at the boundary, keeps every layer below this one
    working with aware datetimes only.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class FollowUpTaskBase(BaseModel):
    """
    Base Pydantic schema for FollowUpTask shared fields.
    """
    title: str = Field(..., description="Short headline describing what needs to be done", min_length=1, max_length=255)
    description: str | None = Field(None, description="Longer detail about the follow-up", max_length=10000)
    follow_up_type: FollowUpType = Field(FollowUpType.CALL, description="Channel through which the follow-up is performed")
    priority: FollowUpPriority = Field(FollowUpPriority.MEDIUM, description="How urgently this task should be worked")
    scheduled_at: datetime = Field(..., description="When this follow-up is due (ISO 8601; naive values are treated as UTC)")
    assigned_employee_id: uuid.UUID | None = Field(None, description="Employee responsible for the follow-up")
    remarks: str | None = Field(None, description="Free-form remarks about the task", max_length=10000)

    @field_validator("title")
    @classmethod
    def title_cannot_be_blank(cls, v: str) -> str:
        """
        Validates the title is not just whitespace, and normalizes it by stripping.
        """
        stripped = v.strip()
        if not stripped:
            raise ValueError("Title cannot be empty or contain only whitespace.")
        return stripped

    @field_validator("scheduled_at")
    @classmethod
    def scheduled_at_must_be_aware(cls, v: datetime) -> datetime:
        return _require_aware(v, "scheduled_at")


class FollowUpTaskCreate(FollowUpTaskBase):
    """
    Schema for validating requests to create a follow-up task.

    `lead_id` is in the body rather than the path because tasks are addressed as a top-level
    `/followups` collection (per the API specification) rather than as a lead sub-resource.
    """
    lead_id: uuid.UUID = Field(..., description="The lead this follow-up task is about")


class FollowUpTaskUpdate(BaseModel):
    """
    Schema for validating requests to edit an existing task.

    Every field is optional so a caller can PATCH-style submit only what changed; the
    service uses `exclude_unset=True` to distinguish "not supplied" from "explicitly set to
    null". `status`/`completed_at` are intentionally absent — see the module docstring.
    """
    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=10000)
    follow_up_type: FollowUpType | None = None
    priority: FollowUpPriority | None = None
    scheduled_at: datetime | None = Field(None, description="Reschedule via PUT /followups/{id}/reschedule to emit a timeline entry; setting it here is a silent correction")
    assigned_employee_id: uuid.UUID | None = None
    remarks: str | None = Field(None, max_length=10000)
    version: int | None = Field(None, description="Expected version for optimistic locking; a mismatch returns 409")

    @field_validator("title")
    @classmethod
    def title_cannot_be_blank(cls, v: str | None) -> str | None:
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            raise ValueError("Title cannot be empty or contain only whitespace.")
        return stripped

    @field_validator("scheduled_at")
    @classmethod
    def scheduled_at_must_be_aware(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        return _require_aware(v, "scheduled_at")


class FollowUpTaskComplete(BaseModel):
    """
    Schema for marking a task complete.
    """
    remarks: str | None = Field(None, description="Outcome notes for what happened", max_length=10000)
    completed_at: datetime | None = Field(None, description="When it was actually done (defaults to now)")

    @field_validator("completed_at")
    @classmethod
    def completed_at_must_be_aware(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        return _require_aware(v, "completed_at")


class FollowUpTaskReschedule(BaseModel):
    """
    Schema for moving a task to a new due time.
    """
    scheduled_at: datetime = Field(..., description="The new due time for the follow-up")
    remarks: str | None = Field(None, description="Why it was rescheduled", max_length=10000)

    @field_validator("scheduled_at")
    @classmethod
    def scheduled_at_must_be_aware(cls, v: datetime) -> datetime:
        return _require_aware(v, "scheduled_at")


class FollowUpTaskAssign(BaseModel):
    """
    Schema for assigning (or unassigning) a task's owner.

    `assigned_employee_id` is required but nullable: an explicit null means "unassign",
    which is a real operation and must be distinguishable from "field omitted".
    """
    assigned_employee_id: uuid.UUID | None = Field(..., description="Employee to assign the task to, or null to unassign")


class FollowUpTaskCancel(BaseModel):
    """
    Schema for cancelling a task.
    """
    remarks: str | None = Field(None, description="Why it was cancelled", max_length=10000)


class FollowUpTaskResponse(BaseModel):
    """
    Schema for serializing a FollowUpTask database record into an API response.

    `is_overdue` is computed rather than stored. Because this phase ships no background
    sweeper, a row's stored `status` can read PENDING while its due time has passed; the
    flag gives clients the truthful answer without making every consumer re-derive it. See
    `app/models/follow_up.py` for the full reasoning.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    assigned_employee_id: uuid.UUID | None
    title: str
    description: str | None
    follow_up_type: FollowUpType
    priority: FollowUpPriority
    status: FollowUpStatus
    scheduled_at: datetime
    completed_at: datetime | None
    remarks: str | None
    is_overdue: bool = Field(False, description="True when the task is still open and its due time has passed")
    version: int
    created_at: datetime
    updated_at: datetime


class FollowUpTaskListResponse(BaseModel):
    """
    Schema for a paginated list of follow-up tasks.
    Ordered soonest-due first, then by descending priority.
    """
    items: List[FollowUpTaskResponse]
    total: int = Field(..., description="Total tasks matching the filters (ignoring skip/limit)")
    skip: int
    limit: int


class FollowUpStatisticsResponse(BaseModel):
    """
    Schema for the follow-up statistics summary.

    The headline counters answer "how is the team doing on follow-ups"; the three
    breakdown dictionaries support charting without a second round trip. `completion_rate`
    is expressed as a percentage of *resolved* tasks (completed + cancelled), not of all
    tasks, so a large backlog of future work does not make the team look unproductive.
    """
    total: int = Field(..., description="All visible tasks")
    pending: int = Field(..., description="Tasks still to be done and not yet past due")
    completed: int = Field(..., description="Tasks marked complete")
    cancelled: int = Field(..., description="Tasks cancelled without being done")
    overdue: int = Field(..., description="Open tasks whose due time has passed")
    due_today: int = Field(..., description="Open tasks due at some point today")
    due_this_week: int = Field(..., description="Open tasks due within the next 7 days")
    completion_rate: float = Field(..., description="Completed as a percentage of resolved (completed + cancelled) tasks")
    by_status: dict[str, int] = Field(..., description="Task counts keyed by status")
    by_type: dict[str, int] = Field(..., description="Task counts keyed by follow-up type")
    by_priority: dict[str, int] = Field(..., description="Task counts keyed by priority")
    assigned_employee_id: uuid.UUID | None = Field(None, description="The employee these statistics were scoped to, if any")
