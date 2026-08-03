"""
app/repositories/lead_activity.py

This file implements the LeadActivityRepository and LeadNoteRepository.
Under Clean Architecture, this file belongs to the Interface Adapters layer.
It encapsulates SQL database access (via SQLAlchemy 2.0), keeping the service layer free
of data access technologies.

Both repositories follow the house convention established in `app/repositories/lead.py`:
`create`/`update`/`delete` take a `commit: bool = True` flag so a service can batch several
writes into a single transaction, and list queries return a `(rows, total)` tuple so the
API layer can build pagination metadata without a second round trip.
"""

import uuid
from typing import Sequence
from datetime import datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_activity import LeadActivity, LeadNote, ActivityType


class LeadActivityRepository:
    """
    LeadActivity Repository.
    Handles append + read access on the lead_activities table.

    There is deliberately no `update` or `delete` method: the timeline is append-only, and
    the absence of those methods is what enforces it at the data-access layer.
    """

    async def create(self, db: AsyncSession, activity: LeadActivity, commit: bool = True) -> LeadActivity:
        """
        Appends a new activity to a lead's timeline.

        Pass `commit=False` when the caller is already inside a transaction that must
        commit the activity atomically with the domain change that produced it.
        """
        db.add(activity)
        if commit:
            await db.commit()
            await db.refresh(activity)
        else:
            # Flush (not commit) so the row is assigned its PK/defaults and is visible to
            # later queries in this same transaction, without ending the transaction.
            await db.flush()
        return activity

    async def get_by_id(self, db: AsyncSession, id: uuid.UUID) -> LeadActivity | None:
        """
        Fetches a single activity by its UUID.
        """
        result = await db.execute(select(LeadActivity).where(LeadActivity.id == id))
        return result.scalars().first()

    async def get_by_lead(
        self,
        db: AsyncSession,
        lead_id: uuid.UUID,
        skip: int = 0,
        limit: int = 50,
        activity_type: ActivityType | None = None,
    ) -> tuple[Sequence[LeadActivity], int]:
        """
        Fetches a lead's timeline, newest first, plus the total count of matching rows
        (ignoring skip/limit) for pagination metadata.

        Ordering is `created_at DESC, id DESC`. The `id` tiebreaker matters: several
        activities emitted inside one transaction can share an identical `created_at`
        (Postgres `now()` is fixed for the whole transaction), and without a deterministic
        secondary sort those rows could shuffle between pages and be duplicated or skipped.
        """
        filters = [LeadActivity.lead_id == lead_id]
        if activity_type:
            filters.append(LeadActivity.activity_type == activity_type)

        count_query = select(func.count()).select_from(LeadActivity).where(*filters)
        total = (await db.execute(count_query)).scalar_one()

        query = (
            select(LeadActivity)
            .where(*filters)
            .order_by(LeadActivity.created_at.desc(), LeadActivity.id.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(query)
        return result.scalars().all(), total


class LeadNoteRepository:
    """
    LeadNote Repository.
    Handles CRUD operations on the lead_notes table.
    Soft-deleted notes are excluded by default, matching the convention in LeadRepository.
    """

    def __init__(self, include_deleted: bool = False) -> None:
        self.include_deleted = include_deleted

    async def create(self, db: AsyncSession, note: LeadNote, commit: bool = True) -> LeadNote:
        """
        Persists a new note.
        """
        db.add(note)
        if commit:
            await db.commit()
            await db.refresh(note)
        else:
            await db.flush()
        return note

    async def get_by_id(self, db: AsyncSession, id: uuid.UUID, include_deleted: bool | None = None) -> LeadNote | None:
        """
        Fetches a single note by its UUID.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(LeadNote).where(LeadNote.id == id)
        if not inc:
            query = query.where(LeadNote.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().first()

    async def get_by_lead(
        self,
        db: AsyncSession,
        lead_id: uuid.UUID,
        skip: int = 0,
        limit: int = 50,
        include_deleted: bool | None = None,
    ) -> tuple[Sequence[LeadNote], int]:
        """
        Fetches a lead's notes, newest first, plus the total count of matching rows
        (ignoring skip/limit) for pagination metadata.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted

        filters = [LeadNote.lead_id == lead_id]
        if not inc:
            filters.append(LeadNote.is_deleted == False)

        count_query = select(func.count()).select_from(LeadNote).where(*filters)
        total = (await db.execute(count_query)).scalar_one()

        query = (
            select(LeadNote)
            .where(*filters)
            .order_by(LeadNote.created_at.desc(), LeadNote.id.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(query)
        return result.scalars().all(), total

    async def update(self, db: AsyncSession, db_obj: LeadNote, update_data: dict, commit: bool = True) -> LeadNote:
        """
        Updates a note's attributes.
        """
        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)

        db.add(db_obj)
        if commit:
            await db.commit()
            await db.refresh(db_obj)
        else:
            await db.flush()
        return db_obj

    async def delete(self, db: AsyncSession, db_obj: LeadNote, commit: bool = True) -> bool:
        """
        Soft deletes a note.
        """
        db_obj.is_deleted = True
        db_obj.deleted_at = datetime.now(timezone.utc)
        db.add(db_obj)
        if commit:
            await db.commit()
        else:
            await db.flush()
        return True


class AdminLeadNoteRepository(LeadNoteRepository):
    """
    LeadNote Repository that includes soft-deleted notes by default.
    Mirrors AdminLeadRepository in app/repositories/lead.py.
    """
    def __init__(self) -> None:
        super().__init__(include_deleted=True)
