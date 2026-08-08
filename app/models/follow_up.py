"""
app/models/follow_up.py

This file defines the SQLAlchemy database model for the Follow-up & Task Management module,
along with its three supporting enums.
Under Clean Architecture, this file belongs to the Enterprise Domain Model layer.

A `FollowUpTask` answers the question the sales team asks every morning: "which leads need
me to do something today?". It is a scheduled unit of work attached to a lead — call them
back, send the quote, meet them on site — owned by one employee and carrying a due time.

Relationship to the Lead Activity module: a task is *intent* ("call this lead on Friday"),
while a `LeadActivity` is *history* ("a call task was created / completed / rescheduled").
Tasks are therefore mutable and deletable, and every mutation emits an immutable activity
onto the lead's timeline. The two must not be collapsed into one table: a timeline you can
edit is not an audit trail, and a worklist you cannot edit is not a worklist.
"""

import enum
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Text, Enum, Boolean, Integer, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.core.database import Base


class FollowUpType(str, enum.Enum):
    """
    Enum describing the channel/medium through which the follow-up will be performed.

    This is the *planned* action, not a record of what happened. A CALL task that ends in a
    WhatsApp exchange stays a CALL task; what actually occurred is captured by the activity
    emitted on completion and by the task's `remarks`.
    """
    CALL = "CALL"
    WHATSAPP = "WHATSAPP"
    MEETING = "MEETING"
    REMINDER = "REMINDER"
    EMAIL = "EMAIL"


class FollowUpPriority(str, enum.Enum):
    """
    Enum representing how urgently a task should be worked relative to its peers.

    Declared low-to-high so that ordering logic can be expressed once, in
    `app/repositories/follow_up.py`, as an explicit rank mapping. Postgres orders a native
    ENUM by declaration order, but the ORM-level ordering used by the worklist queries does
    not rely on that: it sorts on an explicit CASE so the intent survives a future
    re-ordering of these members.
    """
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


class FollowUpStatus(str, enum.Enum):
    """
    Enum representing the lifecycle state of a task.

    PENDING and OVERDUE are deliberately *both* stored states, even though "overdue" is
    derivable from `scheduled_at < now()`. The reason is that OVERDUE is a terminal-ish
    escalation the business wants to record and report on, and this phase explicitly ships
    without a background scheduler — so nothing sweeps PENDING rows into OVERDUE on a timer.

    The consequence, which callers must understand: a row's stored `status` may read
    PENDING while its `scheduled_at` is in the past. Every read path in this module treats
    "overdue" as the *derived* condition (`status == PENDING AND scheduled_at < now()`)
    OR-ed with the stored OVERDUE value, so the worklist is correct with or without a
    sweeper. When the scheduler lands it only has to flip the stored value; no query
    changes.
    """
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    OVERDUE = "OVERDUE"


# The statuses a task can no longer be worked from. Completing, rescheduling or reassigning
# a task in one of these states is rejected by the service layer: re-opening finished work
# silently would make the "what is outstanding" number untrustworthy, which is the single
# thing this module exists to report.
CLOSED_FOLLOW_UP_STATUSES: set[FollowUpStatus] = {
    FollowUpStatus.COMPLETED,
    FollowUpStatus.CANCELLED,
}

# The statuses that count as outstanding work. OVERDUE is open work that is simply late, so
# it belongs here alongside PENDING.
OPEN_FOLLOW_UP_STATUSES: set[FollowUpStatus] = {
    FollowUpStatus.PENDING,
    FollowUpStatus.OVERDUE,
}


class FollowUpTask(Base):
    """
    FollowUpTask database model — one scheduled piece of work against a lead.

    Design Decisions:
    - Primary Key ID: UUIDv4, consistent with every other entity in this system.
    - lead_id: FK to leads.id with ON DELETE CASCADE. A task has no meaning without its
      lead. Leads are only ever soft-deleted by the application, so this cascade fires only
      on a genuine hard delete (test cleanup or an admin purge). Soft-deleting a lead leaves
      its tasks in place, which is why the worklist queries join through to `Lead` and
      filter `Lead.is_deleted == False` rather than trusting the task row alone.
    - assigned_employee_id: nullable FK to employees.id with ON DELETE SET NULL. Nullable
      because a task can legitimately be created unassigned (the automation creates such
      tasks when the lead itself has no owner) and because a task must survive the removal
      of the staff member it was assigned to — losing the work item along with the employee
      would be a silent data loss.
    - Soft delete (`is_deleted`/`deleted_at`) rather than a hard delete, matching the
      convention used by Lead/Order/LeadNote. A deleted task is still evidence of what the
      team planned, and the timeline entry announcing its creation stays truthful.
    - Optimistic locking via `version`, matching Lead and Order. Unlike a note, a task is
      genuinely contended: a manager reassigns it while the assignee is completing it, and
      last-write-wins would silently discard one of those. A stale write raises
      SQLAlchemy's StaleDataError, translated globally into HTTP 409 VERSION_CONFLICT.
    - `scheduled_at` is timezone-aware and NOT NULL: a follow-up with no due time cannot
      appear on a "today" list, which would make it invisible work.
    - `completed_at` is nullable and set only on the transition into COMPLETED. It is
      deliberately not reused for CANCELLED, so "how many did we actually do" stays a
      simple non-null count.

    Indexing follows the three hot queries this table exists to serve, all of which filter
    on an employee and a time window:
    - (assigned_employee_id, scheduled_at) — "my day", the most-run query in the module.
    - (status, scheduled_at) — the overdue sweep and the global worklist.
    - (lead_id, scheduled_at DESC) — a lead's own follow-up history on its detail page.
    """
    __tablename__ = "follow_up_tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier for the follow-up task (UUIDv4)"
    )

    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="The lead this follow-up task is about"
    )

    assigned_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Employee responsible for performing this follow-up (null if unassigned)"
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Short headline describing what needs to be done"
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Longer detail about the follow-up (optional)"
    )

    follow_up_type: Mapped[FollowUpType] = mapped_column(
        Enum(FollowUpType, name="follow_up_type"),
        default=FollowUpType.CALL,
        server_default=FollowUpType.CALL.value,
        nullable=False,
        index=True,
        doc="The channel through which the follow-up is to be performed"
    )

    priority: Mapped[FollowUpPriority] = mapped_column(
        Enum(FollowUpPriority, name="follow_up_priority"),
        default=FollowUpPriority.MEDIUM,
        server_default=FollowUpPriority.MEDIUM.value,
        nullable=False,
        index=True,
        doc="How urgently this task should be worked relative to its peers"
    )

    status: Mapped[FollowUpStatus] = mapped_column(
        Enum(FollowUpStatus, name="follow_up_status"),
        default=FollowUpStatus.PENDING,
        server_default=FollowUpStatus.PENDING.value,
        nullable=False,
        index=True,
        doc="Current lifecycle state of the task"
    )

    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        doc="When this follow-up is due to be performed"
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when the task was marked complete (null unless status is COMPLETED)"
    )

    remarks: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Outcome notes recorded when the task was completed, rescheduled or cancelled"
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
        doc="Timestamp when the task was soft-deleted"
    )

    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
        doc="Optimistic locking version number"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Timestamp when the task was created"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Timestamp when the task was last updated"
    )

    __table_args__ = (
        # "What is on my plate, ordered by when it is due" — the module's hot path.
        Index("ix_follow_up_tasks_employee_scheduled", "assigned_employee_id", "scheduled_at"),
        # The overdue/worklist scan, which filters by state first and then by due time.
        Index("ix_follow_up_tasks_status_scheduled", "status", "scheduled_at"),
        # A single lead's follow-up history, newest-scheduled first.
        Index("ix_follow_up_tasks_lead_scheduled", "lead_id", scheduled_at.desc()),
    )

    # SQLAlchemy mapper configuration for optimistic locking
    __mapper_args__ = {
        "version_id_col": version
    }
