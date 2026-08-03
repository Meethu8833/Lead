"""
app/repositories/import_job.py

This file implements the ImportJobRepository.
Under Clean Architecture, this file belongs to the Interface Adapters layer. It encapsulates
SQL access for the `import_jobs` table and returns ORM objects for the service layer to act
on, keeping SQL out of `LeadImportService`.

The one non-obvious method here is `append_log`, which exists because a run's diagnostics
accumulate across many records: rewriting the whole JSONB array from Python on every entry
would be both wasteful and racy. See its docstring.
"""

import uuid
from typing import Any, Sequence
from datetime import datetime, timezone
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.import_job import ImportJob, ImportJobStatus


class ImportJobRepository:
    """
    ImportJob Repository.
    Handles CRUD and querying for lead-collection import runs.
    """

    def __init__(self, include_deleted: bool = False) -> None:
        self.include_deleted = include_deleted

    async def create(self, db: AsyncSession, job: ImportJob, commit: bool = True) -> ImportJob:
        """
        Persists a new ImportJob record.
        """
        db.add(job)
        if commit:
            await db.commit()
            await db.refresh(job)
        else:
            await db.flush()
        return job

    async def get_by_id(
        self,
        db: AsyncSession,
        id: uuid.UUID,
        include_deleted: bool | None = None,
    ) -> ImportJob | None:
        """
        Fetches a single ImportJob by its UUID.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(ImportJob).where(ImportJob.id == id)
        if not inc:
            query = query.where(ImportJob.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().first()

    def _apply_filters(
        self,
        query,
        provider: str | None = None,
        status: ImportJobStatus | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        include_deleted: bool = False,
    ):
        """
        Applies the shared filter predicate set to a base ImportJob select() query.
        """
        filters = []
        if provider:
            filters.append(ImportJob.provider == provider.strip().lower())
        if status:
            filters.append(ImportJob.status == status)
        if created_from:
            filters.append(ImportJob.created_at >= created_from)
        if created_to:
            filters.append(ImportJob.created_at <= created_to)
        if not include_deleted:
            filters.append(ImportJob.is_deleted == False)

        if filters:
            query = query.where(and_(*filters))
        return query

    async def get_all(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        provider: str | None = None,
        status: ImportJobStatus | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        include_deleted: bool | None = None,
    ) -> tuple[Sequence[ImportJob], int]:
        """
        Fetches a paginated, filtered list of import jobs plus the total count of matching
        rows (ignoring skip/limit) for pagination metadata.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted

        base_query = self._apply_filters(
            select(ImportJob),
            provider=provider,
            status=status,
            created_from=created_from,
            created_to=created_to,
            include_deleted=inc,
        )
        count_query = self._apply_filters(
            select(func.count()).select_from(ImportJob),
            provider=provider,
            status=status,
            created_from=created_from,
            created_to=created_to,
            include_deleted=inc,
        )

        total_result = await db.execute(count_query)
        total = total_result.scalar_one()

        query = base_query.order_by(ImportJob.created_at.desc()).offset(skip).limit(limit)
        result = await db.execute(query)
        return result.scalars().all(), total

    async def update(
        self,
        db: AsyncSession,
        db_obj: ImportJob,
        update_data: dict,
        commit: bool = True,
    ) -> ImportJob:
        """
        Updates a job's attributes and (by default) commits.
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

    async def append_logs(
        self,
        db: AsyncSession,
        db_obj: ImportJob,
        entries: list[dict[str, Any]],
        commit: bool = True,
    ) -> ImportJob:
        """
        Appends diagnostic entries to a job's `logs` array.

        The array is rebuilt as a new Python list rather than mutated in place: SQLAlchemy
        does not track in-place mutation of a plain JSONB column, so `job.logs.append(...)`
        would leave the ORM believing nothing changed and the entries would never reach the
        database. Reassignment is what marks the attribute dirty.

        Entries are appended in one call per batch rather than one call per record so a
        200-record run issues one UPDATE, not 200.
        """
        if not entries:
            return db_obj
        existing = list(db_obj.logs or [])
        existing.extend(entries)
        db_obj.logs = existing
        db.add(db_obj)
        if commit:
            await db.commit()
            await db.refresh(db_obj)
        else:
            await db.flush()
        return db_obj

    async def delete(self, db: AsyncSession, db_obj: ImportJob, commit: bool = True) -> bool:
        """
        Soft deletes an import job record.
        """
        db_obj.is_deleted = True
        db_obj.deleted_at = datetime.now(timezone.utc)
        db.add(db_obj)
        if commit:
            await db.commit()
        else:
            await db.flush()
        return True

    async def get_statistics(self, db: AsyncSession) -> dict[str, Any]:
        """
        Aggregates lifetime import statistics across all non-deleted jobs.

        Computed in SQL rather than by loading rows because the history grows without bound
        and the numbers are only ever displayed in aggregate.
        """
        query = select(
            func.count().label("total_jobs"),
            func.coalesce(func.sum(ImportJob.total_found), 0).label("total_found"),
            func.coalesce(func.sum(ImportJob.new_leads), 0).label("new_leads"),
            func.coalesce(func.sum(ImportJob.updated_leads), 0).label("updated_leads"),
            func.coalesce(func.sum(ImportJob.duplicate_leads), 0).label("duplicate_leads"),
            func.coalesce(func.sum(ImportJob.failed_records), 0).label("failed_records"),
        ).where(ImportJob.is_deleted == False)

        row = (await db.execute(query)).one()

        status_query = (
            select(ImportJob.status, func.count())
            .where(ImportJob.is_deleted == False)
            .group_by(ImportJob.status)
        )
        status_rows = (await db.execute(status_query)).all()

        return {
            "total_jobs": row.total_jobs,
            "total_found": row.total_found,
            "new_leads": row.new_leads,
            "updated_leads": row.updated_leads,
            "duplicate_leads": row.duplicate_leads,
            "failed_records": row.failed_records,
            "jobs_by_status": {
                (status.value if hasattr(status, "value") else str(status)): count
                for status, count in status_rows
            },
        }


class AdminImportJobRepository(ImportJobRepository):
    """
    ImportJob Repository that includes soft-deleted items by default.
    """
    def __init__(self) -> None:
        super().__init__(include_deleted=True)
