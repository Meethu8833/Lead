"""
app/services/lead_activity.py

This file implements LeadActivityService and LeadNoteService.
Under Clean Architecture, this file belongs to the Application Business Rules (Use Cases) layer.

LeadActivityService is the single writer of the lead timeline. Every automatic activity in
the system funnels through its `record()` method, which means the shape of a timeline entry
is defined in exactly one place. LeadService calls the `log_*` convenience methods rather
than constructing `LeadActivity` rows itself, so the Lead module stays unaware of the
timeline's internals.

Actor resolution: the acting employee is read from the request-scoped `audit_context`
ContextVar (populated by `audit_middleware` in app/main.py) unless a caller passes one
explicitly. This is the same source the automatic audit-log listener uses, so an activity
and its corresponding audit row always agree on who did the thing, and no `employee_id`
parameter has to be threaded through every service signature.
"""

import uuid
from typing import Any, Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import audit_context
from app.core.exceptions import BadRequestException, NotFoundException
from app.models.employee import Employee
from app.models.lead import Lead, LeadStatus
from app.models.lead_activity import LeadActivity, LeadNote, ActivityType
from app.repositories.lead_activity import LeadActivityRepository, LeadNoteRepository
from app.repositories.lead import LeadRepository
from app.schemas.lead_activity import LeadNoteCreate, LeadNoteUpdate


# Lead columns that are pure bookkeeping rather than meaningful business changes.
# They are excluded from the UPDATED activity's changed-field list so the timeline shows
# "phone, city changed", not "phone, city, version, updated_at changed".
_NON_MEANINGFUL_UPDATE_FIELDS = {"version", "updated_at", "created_at", "id"}


def _context_actor_uuid() -> uuid.UUID | None:
    """
    Parses the acting user out of the request-scoped audit context as a UUID.

    Returns None when there is no context, or when the context holds a non-UUID actor
    such as the literal "SYSTEM" used by background jobs.
    """
    ctx = audit_context.get()
    if not ctx:
        return None
    raw = ctx.get("user_id")
    if not raw:
        return None
    if isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        return None


async def resolve_actor_employee_id(db: AsyncSession) -> uuid.UUID | None:
    """
    Resolves the acting employee for an activity/note, or None for a system-generated one.

    The audit context is populated by `audit_middleware` from the caller-supplied
    `x-user-id` / `x-performed-by` request headers, which are NOT authenticated and may
    hold any string at all. `AuditLog.performed_by` is free text so it can store that
    verbatim, but `created_by_employee_id` is a real FK to `employees.id` — writing an
    unverified value there would raise ForeignKeyViolationError and fail the whole request.

    So the parsed UUID is confirmed against the employees table before it is used, and
    falls back to None (a system-generated entry) when it does not resolve. Degrading the
    attribution is always preferable to failing the domain operation being recorded.
    """
    candidate = _context_actor_uuid()
    if candidate is None:
        return None

    exists = await db.scalar(select(Employee.id).where(Employee.id == candidate))
    return exists


class LeadActivityService:
    """
    Service layer owning the lead timeline: writes activities and reads them back.
    """

    def __init__(
        self,
        repository: LeadActivityRepository | None = None,
        lead_repository: LeadRepository | None = None,
    ) -> None:
        self.repository = repository or LeadActivityRepository()
        self.lead_repository = lead_repository or LeadRepository()

    # -----------------------------------------------------------------
    # WRITE
    # -----------------------------------------------------------------

    async def record(
        self,
        db: AsyncSession,
        lead_id: uuid.UUID,
        activity_type: ActivityType,
        title: str,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
        employee_id: uuid.UUID | None = None,
        commit: bool = True,
    ) -> LeadActivity:
        """
        Appends one entry to a lead's timeline. This is the single write path for
        activities; every `log_*` helper below delegates here.

        `employee_id` defaults to the actor in the request-scoped audit context.
        `commit=False` lets the caller keep the activity in the same transaction as the
        domain change it describes.
        """
        activity = LeadActivity(
            lead_id=lead_id,
            activity_type=activity_type,
            title=title,
            description=description,
            activity_metadata=metadata,
            created_by_employee_id=(
                employee_id if employee_id is not None else await resolve_actor_employee_id(db)
            ),
        )
        return await self.repository.create(db, activity, commit=commit)

    # -----------------------------------------------------------------
    # AUTOMATIC ACTIVITY HOOKS
    # These are called by LeadService at the corresponding domain events.
    # -----------------------------------------------------------------

    async def log_created(self, db: AsyncSession, lead: Lead, commit: bool = True) -> LeadActivity:
        """
        Records that a lead entered the pipeline.
        """
        return await self.record(
            db,
            lead_id=lead.id,
            activity_type=ActivityType.CREATED,
            title="Lead created",
            description=f"Lead '{lead.business_name}' was added to the pipeline.",
            metadata={
                "business_name": lead.business_name,
                "phone": lead.phone,
                "source": lead.source.value if lead.source else None,
                "status": lead.status.value if lead.status else None,
            },
            commit=commit,
        )

    async def log_updated(
        self,
        db: AsyncSession,
        lead: Lead,
        changes: dict[str, dict[str, Any]],
        commit: bool = True,
    ) -> LeadActivity | None:
        """
        Records a generic field update.

        `changes` maps field name -> {"old": ..., "new": ...}. Returns None (writing
        nothing) when no meaningful field actually changed, so that a no-op PUT does not
        pollute the timeline with an empty "updated" entry.
        """
        meaningful = {k: v for k, v in changes.items() if k not in _NON_MEANINGFUL_UPDATE_FIELDS}
        if not meaningful:
            return None

        field_list = ", ".join(sorted(meaningful.keys()))
        return await self.record(
            db,
            lead_id=lead.id,
            activity_type=ActivityType.UPDATED,
            title="Lead updated",
            description=f"Updated field(s): {field_list}.",
            metadata={"changes": meaningful},
            commit=commit,
        )

    async def log_status_changed(
        self,
        db: AsyncSession,
        lead: Lead,
        old_status: LeadStatus | str | None,
        new_status: LeadStatus | str | None,
        commit: bool = True,
    ) -> LeadActivity:
        """
        Records a CRM lifecycle status transition. Emitted in addition to (not instead of)
        the generic UPDATED entry, because "who moved this lead to NEGOTIATION and when" is
        the single most-queried fact in the timeline and deserves its own filterable type.
        """
        old_val = old_status.value if isinstance(old_status, LeadStatus) else old_status
        new_val = new_status.value if isinstance(new_status, LeadStatus) else new_status
        return await self.record(
            db,
            lead_id=lead.id,
            activity_type=ActivityType.STATUS_CHANGED,
            title=f"Status changed: {old_val} → {new_val}",
            description=f"Lead status moved from {old_val} to {new_val}.",
            metadata={"old_status": old_val, "new_status": new_val},
            commit=commit,
        )

    async def log_converted(self, db: AsyncSession, lead: Lead, commit: bool = True) -> LeadActivity:
        """
        Records that a lead converted into a customer.
        """
        return await self.record(
            db,
            lead_id=lead.id,
            activity_type=ActivityType.CONVERTED,
            title="Lead converted",
            description=f"Lead '{lead.business_name}' was converted into a customer.",
            metadata={
                "business_name": lead.business_name,
                "status": lead.status.value if lead.status else None,
            },
            commit=commit,
        )

    async def log_deleted(self, db: AsyncSession, lead: Lead, commit: bool = True) -> LeadActivity:
        """
        Records that a lead was (soft) deleted.

        The activity row survives, because leads are only soft-deleted in this system and
        the timeline must still explain where the lead went. A genuine hard delete cascades
        the activities away along with the lead, which is the correct outcome there.
        """
        return await self.record(
            db,
            lead_id=lead.id,
            activity_type=ActivityType.DELETED,
            title="Lead deleted",
            description=f"Lead '{lead.business_name}' was deleted.",
            metadata={"business_name": lead.business_name},
            commit=commit,
        )

    async def log_note_added(
        self,
        db: AsyncSession,
        note: LeadNote,
        commit: bool = True,
    ) -> LeadActivity:
        """
        Records that a manual note was written, so the note surfaces on the timeline.
        `metadata.note_id` lets the frontend link the timeline entry back to the live
        (and possibly since-edited) note body.
        """
        preview = note.note if len(note.note) <= 200 else note.note[:197] + "..."
        return await self.record(
            db,
            lead_id=note.lead_id,
            activity_type=ActivityType.NOTE,
            title="Note added",
            description=preview,
            metadata={"note_id": str(note.id)},
            employee_id=note.created_by_employee_id,
            commit=commit,
        )

    # -----------------------------------------------------------------
    # READ
    # -----------------------------------------------------------------

    async def get_lead_timeline(
        self,
        db: AsyncSession,
        lead_id: uuid.UUID,
        skip: int = 0,
        limit: int = 50,
        activity_type: ActivityType | None = None,
    ) -> tuple[Sequence[LeadActivity], int]:
        """
        Returns a lead's timeline newest-first, paginated.
        Raises NotFoundException if the lead does not exist (or is soft-deleted), so the
        endpoint cannot be used to probe for the existence of lead IDs.
        """
        lead = await self.lead_repository.get_by_id(db, lead_id)
        if not lead:
            raise NotFoundException(f"Lead with ID '{lead_id}' was not found.")

        return await self.repository.get_by_lead(
            db, lead_id=lead_id, skip=skip, limit=limit, activity_type=activity_type
        )


class LeadNoteService:
    """
    Service layer for manual notes on a lead.
    Owns the rule that creating a note also emits a NOTE activity onto the timeline.
    """

    def __init__(
        self,
        repository: LeadNoteRepository | None = None,
        lead_repository: LeadRepository | None = None,
        activity_service: LeadActivityService | None = None,
    ) -> None:
        self.repository = repository or LeadNoteRepository()
        self.lead_repository = lead_repository or LeadRepository()
        self.activity_service = activity_service or LeadActivityService()

    async def _get_lead_or_404(self, db: AsyncSession, lead_id: uuid.UUID) -> Lead:
        lead = await self.lead_repository.get_by_id(db, lead_id)
        if not lead:
            raise NotFoundException(f"Lead with ID '{lead_id}' was not found.")
        return lead

    async def create_note(
        self,
        db: AsyncSession,
        lead_id: uuid.UUID,
        schema: LeadNoteCreate,
    ) -> LeadNote:
        """
        Creates a note on a lead and emits the matching NOTE activity.

        Business Rules:
        - The lead must exist and not be soft-deleted.
        - The note body cannot be blank (also enforced at the schema layer).
        - The note and its activity are committed together in one transaction, so the
          timeline can never disagree with the notes list.
        """
        await self._get_lead_or_404(db, lead_id)

        body = schema.note.strip()
        if not body:
            raise BadRequestException("Note cannot be empty.")

        note = LeadNote(
            lead_id=lead_id,
            note=body,
            created_by_employee_id=await resolve_actor_employee_id(db),
        )
        # commit=False on both writes, then a single commit below, so a failure to write
        # the activity rolls the note back with it.
        await self.repository.create(db, note, commit=False)
        await self.activity_service.log_note_added(db, note, commit=False)
        await db.commit()
        await db.refresh(note)
        return note

    async def get_notes_by_lead(
        self,
        db: AsyncSession,
        lead_id: uuid.UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[Sequence[LeadNote], int]:
        """
        Returns a lead's notes newest-first, paginated.
        Raises NotFoundException if the lead does not exist.
        """
        await self._get_lead_or_404(db, lead_id)
        return await self.repository.get_by_lead(db, lead_id=lead_id, skip=skip, limit=limit)

    async def get_note_by_id(self, db: AsyncSession, id: uuid.UUID) -> LeadNote:
        """
        Retrieves a single note by ID. Raises NotFoundException if missing or soft-deleted.
        """
        note = await self.repository.get_by_id(db, id)
        if not note:
            raise NotFoundException(f"Note with ID '{id}' was not found.")
        return note

    async def update_note(
        self,
        db: AsyncSession,
        id: uuid.UUID,
        schema: LeadNoteUpdate,
    ) -> LeadNote:
        """
        Edits a note's body.

        Editing does NOT emit a new activity. The timeline records that a note was written;
        rewording it later is not a new interaction with the lead. The edit is still fully
        captured by the automatic audit-log listener (old/new values on the LeadNote row),
        which is the correct place for that level of detail.
        """
        note = await self.get_note_by_id(db, id)

        body = schema.note.strip()
        if not body:
            raise BadRequestException("Note cannot be empty.")

        return await self.repository.update(db, db_obj=note, update_data={"note": body})

    async def delete_note(self, db: AsyncSession, id: uuid.UUID) -> None:
        """
        Soft deletes a note. The NOTE activity announcing it is intentionally left in place
        so the timeline remains a faithful record of what happened and when.
        """
        note = await self.get_note_by_id(db, id)
        await self.repository.delete(db, db_obj=note)
