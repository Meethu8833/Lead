"""
app/models/lead_activity.py

This file defines the SQLAlchemy database models for the Lead Activity & Notes module,
along with the ActivityType enum.
Under Clean Architecture, this file belongs to the Enterprise Domain Model layer.

Two entities live here because they are two halves of the same feature: the Lead Details
timeline.

- `LeadActivity` is the append-only, system-generated chronological record of everything
  that happened to a lead (created, updated, status changed, converted, a note was added,
  and later WhatsApp/call events). It is deliberately NOT editable or deletable through
  the API: a timeline that can be rewritten is not an audit trail.
- `LeadNote` is the human-authored, editable free-text commentary on a lead. Adding a note
  emits a `NOTE` activity so the note surfaces in the timeline, but the note body itself
  lives in its own table so it can be edited and deleted without corrupting history.
"""

import enum
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Text, Enum, Boolean, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.core.database import Base


class ActivityType(str, enum.Enum):
    """
    Enum describing what kind of interaction a timeline entry represents.

    The WHATSAPP_* members are defined now (the timeline schema must be stable before
    the messaging integration lands) but nothing in this phase emits them — WhatsApp
    automation is explicitly out of scope.
    """
    CREATED = "CREATED"
    UPDATED = "UPDATED"
    WHATSAPP_SENT = "WHATSAPP_SENT"
    WHATSAPP_DELIVERED = "WHATSAPP_DELIVERED"
    WHATSAPP_READ = "WHATSAPP_READ"
    WHATSAPP_REPLIED = "WHATSAPP_REPLIED"
    PHONE_CALL = "PHONE_CALL"
    FOLLOW_UP = "FOLLOW_UP"
    # Follow-up & Task Management lifecycle. FOLLOW_UP above is retained as the generic
    # "a follow-up happened" marker; the four members below are the specific, filterable
    # task events emitted by FollowUpTaskService. They are distinct types rather than one
    # FOLLOW_UP type with a metadata discriminator because "show me every task completed
    # this week" must be an indexed query on activity_type, not a JSONB scan.
    TASK_CREATED = "TASK_CREATED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_RESCHEDULED = "TASK_RESCHEDULED"
    TASK_CANCELLED = "TASK_CANCELLED"
    MEETING_SCHEDULED = "MEETING_SCHEDULED"
    NOTE = "NOTE"
    STATUS_CHANGED = "STATUS_CHANGED"
    CONVERTED = "CONVERTED"
    DELETED = "DELETED"


class LeadActivity(Base):
    """
    LeadActivity database model — one immutable entry in a lead's timeline.

    Design Decisions:
    - Primary Key ID: UUIDv4, consistent with every other entity in this system.
    - lead_id: FK to leads.id with ON DELETE CASCADE. A lead's timeline has no meaning
      without the lead. Note that the application only ever *soft* deletes leads, so this
      cascade fires solely on a genuine hard delete (e.g. test cleanup or an admin purge).
    - created_by_employee_id: nullable FK to employees.id with ON DELETE SET NULL. It is
      nullable both because history must survive the removal of the staff member who made
      it, and because system-generated activities may have no acting employee at all.
    - No `version` column and no `is_deleted` column: activities are append-only, so there
      is nothing to concurrently update and nothing to soft delete.
    - `activity_metadata` maps to the DB column literally named `metadata`. The Python
      attribute must be renamed because `metadata` is reserved by SQLAlchemy's declarative
      base (it holds the MetaData registry); the API layer exposes it as `metadata` again.
    - Composite index on (lead_id, created_at DESC) because the single hot query for this
      table is "newest N activities for one lead".
    """
    __tablename__ = "lead_activities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier for the activity entry (UUIDv4)"
    )

    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="The lead this timeline entry belongs to"
    )

    activity_type: Mapped[ActivityType] = mapped_column(
        Enum(ActivityType, name="lead_activity_type"),
        nullable=False,
        index=True,
        doc="What kind of interaction this entry records"
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Short human-readable headline for the timeline entry"
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Longer human-readable detail for the timeline entry (optional)"
    )

    created_by_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Employee who performed the action (null for system-generated activities)"
    )

    activity_metadata: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        doc="Structured machine-readable payload for the activity (e.g. changed fields, old/new status)"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
        doc="Timestamp when the activity occurred"
    )

    __table_args__ = (
        # The timeline query is always "activities for one lead, newest first".
        Index("ix_lead_activities_lead_id_created_at", "lead_id", created_at.desc()),
    )


class LeadNote(Base):
    """
    LeadNote database model — editable free-text commentary attached to a lead.

    Design Decisions:
    - Soft delete (`is_deleted`/`deleted_at`) rather than a hard delete, matching the
      convention used by every other entity in this system, so a deleted note can still be
      reconstructed from history/audit if needed.
    - No optimistic-locking `version` column. Notes are short single-author free text where
      last-write-wins is the expected behaviour; there is no derived financial or workflow
      state to protect, unlike Lead/Order. This is a deliberate divergence from the Lead
      model, not an omission.
    - Deleting a note does NOT delete the `NOTE` activity that announced it. The timeline
      records that a note was written at that moment, which remains true.
    """
    __tablename__ = "lead_notes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier for the note (UUIDv4)"
    )

    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="The lead this note belongs to"
    )

    note: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="The free-text body of the note"
    )

    created_by_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Employee who authored the note (null if the author record was removed)"
    )

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        doc="Soft delete flag"
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when the note was soft-deleted"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Timestamp when the note was created"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Timestamp when the note was last edited"
    )
