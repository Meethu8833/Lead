"""
app/repositories/follow_up.py

This file implements the FollowUpTaskRepository.
Under Clean Architecture, this file belongs to the Interface Adapters layer.
It encapsulates SQL database access (via SQLAlchemy 2.0), keeping the service layer free of
data access technologies.

It follows the house conventions established in `app/repositories/lead.py`:
`create`/`update`/`delete` take a `commit: bool = True` flag so a service can batch several
writes into one transaction, list queries return a `(rows, total)` tuple so the API layer
can build pagination metadata without a second round trip, and soft-deleted rows are
excluded by default with an `Admin*` subclass that includes them.

Two rules are implemented here rather than in the service, because they must hold for every
caller of every query in this module:

1. **A task belonging to a soft-deleted lead is never returned.** Soft-deleting a lead does
   not cascade to its tasks (the FK cascade only fires on a hard delete), so without an
   explicit join a deleted lead would keep pushing work onto someone's "today" list. Every
   read below joins `Lead` and filters `Lead.is_deleted == False`.

2. **"Overdue" is a derived condition, not just a stored status.** This phase ships without
   a background scheduler, so nothing flips a past-due PENDING row to OVERDUE on a timer.
   `_is_overdue_clause` therefore treats a row as overdue when it is *either* stored as
   OVERDUE *or* still open with `scheduled_at` in the past. The worklist is correct today
   and stays correct once a sweeper lands.
"""

import uuid
from typing import Sequence
from datetime import datetime, timezone
from sqlalchemy import select, func, and_, or_, case, ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.follow_up import (
    FollowUpTask,
    FollowUpType,
    FollowUpPriority,
    FollowUpStatus,
)
from app.models.lead import Lead


# Explicit priority ranking for ordering. The worklist sorts URGENT first, and relying on
# the Postgres ENUM's declaration order to deliver that would silently break if a member
# were ever inserted out of order. Encoding the rank here makes the intent survive that.
_PRIORITY_RANK: dict[FollowUpPriority, int] = {
    FollowUpPriority.URGENT: 0,
    FollowUpPriority.HIGH: 1,
    FollowUpPriority.MEDIUM: 2,
    FollowUpPriority.LOW: 3,
}


def priority_rank_expression() -> ColumnElement:
    """
    Builds the SQL CASE expression that maps a task's priority onto its sort rank
    (0 = most urgent). Exposed so the statistics query can reuse the exact same ordering.
    """
    return case(_PRIORITY_RANK, value=FollowUpTask.priority, else_=len(_PRIORITY_RANK))


class FollowUpTaskRepository:
    """
    FollowUpTask Repository.
    Handles CRUD and worklist queries on the follow_up_tasks table.
    Soft-deleted tasks are excluded by default, matching the convention in LeadRepository.
    """

    def __init__(self, include_deleted: bool = False) -> None:
        self.include_deleted = include_deleted

    # -----------------------------------------------------------------
    # SHARED QUERY FRAGMENTS
    # -----------------------------------------------------------------

    @staticmethod
    def _is_overdue_clause(now: datetime) -> ColumnElement[bool]:
        """
        The definition of "overdue", used by both the overdue worklist and the statistics.

        A task is overdue when it is explicitly stored as OVERDUE, or when it is still
        PENDING and its due time has passed. See the module docstring for why both halves
        are needed while no background sweeper exists.
        """
        return or_(
            FollowUpTask.status == FollowUpStatus.OVERDUE,
            and_(
                FollowUpTask.status == FollowUpStatus.PENDING,
                FollowUpTask.scheduled_at < now,
            ),
        )

    def _base_query(self, include_deleted: bool | None = None):
        """
        Builds the SELECT every read path starts from: tasks joined to their lead, with
        soft-deleted tasks and tasks of soft-deleted leads filtered out.

        The join to `Lead` is an inner join, so a task whose lead was hard-deleted is
        excluded too — though the FK cascade means such a row cannot exist.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(FollowUpTask).join(Lead, FollowUpTask.lead_id == Lead.id).where(
            Lead.is_deleted == False
        )
        if not inc:
            query = query.where(FollowUpTask.is_deleted == False)
        return query

    def _count_query(self, include_deleted: bool | None = None):
        """
        The COUNT(*) mirror of `_base_query`, sharing the identical filter set so a
        paginated list's `total` can never disagree with the rows it accompanies.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = (
            select(func.count())
            .select_from(FollowUpTask)
            .join(Lead, FollowUpTask.lead_id == Lead.id)
            .where(Lead.is_deleted == False)
        )
        if not inc:
            query = query.where(FollowUpTask.is_deleted == False)
        return query

    @staticmethod
    def _worklist_order(query):
        """
        Applies the canonical worklist ordering: soonest due first, then most urgent, then
        a deterministic `id` tiebreaker.

        The `id` tiebreaker is load-bearing, not cosmetic. Tasks created in one transaction
        share an identical `scheduled_at` down to the microsecond in the automation path,
        and without a stable secondary sort those rows could shuffle between pages of a
        paginated worklist and be duplicated or skipped.
        """
        return query.order_by(
            FollowUpTask.scheduled_at.asc(),
            priority_rank_expression().asc(),
            FollowUpTask.id.asc(),
        )

    # -----------------------------------------------------------------
    # WRITE
    # -----------------------------------------------------------------

    async def create(self, db: AsyncSession, task: FollowUpTask, commit: bool = True) -> FollowUpTask:
        """
        Persists a new follow-up task.

        Pass `commit=False` when the caller is already inside a transaction that must commit
        the task atomically with the activity describing it.
        """
        db.add(task)
        if commit:
            await db.commit()
            await db.refresh(task)
        else:
            # Flush (not commit) so the row gets its PK/defaults and is visible to later
            # queries in this same transaction, without ending the transaction.
            await db.flush()
        return task

    async def update(
        self,
        db: AsyncSession,
        db_obj: FollowUpTask,
        update_data: dict,
        commit: bool = True,
    ) -> FollowUpTask:
        """
        Updates a task's attributes.

        Writing any field bumps `version` through the mapper's optimistic-locking config, so
        a concurrent stale write raises StaleDataError rather than silently winning.
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

    async def delete(self, db: AsyncSession, db_obj: FollowUpTask, commit: bool = True) -> bool:
        """
        Soft deletes a task.
        """
        db_obj.is_deleted = True
        db_obj.deleted_at = datetime.now(timezone.utc)
        db.add(db_obj)
        if commit:
            await db.commit()
        else:
            await db.flush()
        return True

    # -----------------------------------------------------------------
    # READ — SINGLE
    # -----------------------------------------------------------------

    async def get_by_id(
        self,
        db: AsyncSession,
        id: uuid.UUID,
        include_deleted: bool | None = None,
    ) -> FollowUpTask | None:
        """
        Fetches a single task by its UUID.

        Deliberately does NOT join `Lead`: an individual task must remain fetchable (and
        therefore deletable/inspectable) even after its lead was soft-deleted. The
        lead-visibility rule applies to the worklists, which are about what to work on
        next — not to direct addressing of a known row.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(FollowUpTask).where(FollowUpTask.id == id)
        if not inc:
            query = query.where(FollowUpTask.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().first()

    async def find_open_duplicate(
        self,
        db: AsyncSession,
        lead_id: uuid.UUID,
        follow_up_type: FollowUpType,
    ) -> FollowUpTask | None:
        """
        Finds an existing open (PENDING/OVERDUE) task of the given type on a lead.

        This backs the automation's de-duplication rule: a lead that replies "interested"
        three times in an afternoon should end up with one call task, not three. It is
        scoped to *open* tasks only, so a genuinely new follow-up after the previous one was
        completed does get created.
        """
        query = (
            select(FollowUpTask)
            .where(
                FollowUpTask.lead_id == lead_id,
                FollowUpTask.follow_up_type == follow_up_type,
                FollowUpTask.is_deleted == False,
                FollowUpTask.status.in_([FollowUpStatus.PENDING, FollowUpStatus.OVERDUE]),
            )
            .order_by(FollowUpTask.scheduled_at.asc())
            .limit(1)
        )
        result = await db.execute(query)
        return result.scalars().first()

    # -----------------------------------------------------------------
    # READ — LISTS
    # -----------------------------------------------------------------

    def _apply_filters(
        self,
        query,
        lead_id: uuid.UUID | None = None,
        assigned_employee_id: uuid.UUID | None = None,
        status: FollowUpStatus | None = None,
        follow_up_type: FollowUpType | None = None,
        priority: FollowUpPriority | None = None,
        scheduled_from: datetime | None = None,
        scheduled_to: datetime | None = None,
        search: str | None = None,
    ):
        """
        Applies the optional filter set shared by the list query and its count query.

        `scheduled_from`/`scheduled_to` form a half-open window `[from, to)`. Half-open
        rather than inclusive-both-ends because these windows are used to slice contiguous
        days: an inclusive upper bound would make a task due at exactly midnight appear on
        both days.
        """
        if lead_id is not None:
            query = query.where(FollowUpTask.lead_id == lead_id)
        if assigned_employee_id is not None:
            query = query.where(FollowUpTask.assigned_employee_id == assigned_employee_id)
        if status is not None:
            query = query.where(FollowUpTask.status == status)
        if follow_up_type is not None:
            query = query.where(FollowUpTask.follow_up_type == follow_up_type)
        if priority is not None:
            query = query.where(FollowUpTask.priority == priority)
        if scheduled_from is not None:
            query = query.where(FollowUpTask.scheduled_at >= scheduled_from)
        if scheduled_to is not None:
            query = query.where(FollowUpTask.scheduled_at < scheduled_to)
        if search:
            term = f"%{search.strip()}%"
            query = query.where(
                or_(
                    FollowUpTask.title.ilike(term),
                    FollowUpTask.description.ilike(term),
                )
            )
        return query

    async def get_all(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 50,
        lead_id: uuid.UUID | None = None,
        assigned_employee_id: uuid.UUID | None = None,
        status: FollowUpStatus | None = None,
        follow_up_type: FollowUpType | None = None,
        priority: FollowUpPriority | None = None,
        scheduled_from: datetime | None = None,
        scheduled_to: datetime | None = None,
        search: str | None = None,
        include_deleted: bool | None = None,
    ) -> tuple[Sequence[FollowUpTask], int]:
        """
        Fetches a filtered, paginated list of tasks plus the total count of matching rows
        (ignoring skip/limit) for pagination metadata.
        """
        filter_kwargs = dict(
            lead_id=lead_id,
            assigned_employee_id=assigned_employee_id,
            status=status,
            follow_up_type=follow_up_type,
            priority=priority,
            scheduled_from=scheduled_from,
            scheduled_to=scheduled_to,
            search=search,
        )

        count_query = self._apply_filters(self._count_query(include_deleted), **filter_kwargs)
        total = (await db.execute(count_query)).scalar_one()

        query = self._apply_filters(self._base_query(include_deleted), **filter_kwargs)
        query = self._worklist_order(query).offset(skip).limit(limit)
        result = await db.execute(query)
        return result.scalars().all(), total

    async def get_due_between(
        self,
        db: AsyncSession,
        start: datetime,
        end: datetime,
        assigned_employee_id: uuid.UUID | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[Sequence[FollowUpTask], int]:
        """
        Fetches *open* tasks due in the half-open window `[start, end)`.

        This backs both "today's follow-ups" and "upcoming follow-ups", which differ only in
        the window they pass. Closed tasks (COMPLETED/CANCELLED) are excluded because these
        are worklists — a finished task is not something to do today.
        """
        open_statuses = [FollowUpStatus.PENDING, FollowUpStatus.OVERDUE]
        filters = [
            FollowUpTask.status.in_(open_statuses),
            FollowUpTask.scheduled_at >= start,
            FollowUpTask.scheduled_at < end,
        ]
        if assigned_employee_id is not None:
            filters.append(FollowUpTask.assigned_employee_id == assigned_employee_id)

        total = (await db.execute(self._count_query().where(*filters))).scalar_one()

        query = self._worklist_order(self._base_query().where(*filters)).offset(skip).limit(limit)
        result = await db.execute(query)
        return result.scalars().all(), total

    async def get_overdue(
        self,
        db: AsyncSession,
        now: datetime,
        assigned_employee_id: uuid.UUID | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[Sequence[FollowUpTask], int]:
        """
        Fetches tasks that are past due and still open, oldest-due first.

        Ordering ascending on `scheduled_at` puts the longest-neglected lead at the top,
        which is the order the team needs to work them in.
        """
        filters = [self._is_overdue_clause(now)]
        if assigned_employee_id is not None:
            filters.append(FollowUpTask.assigned_employee_id == assigned_employee_id)

        total = (await db.execute(self._count_query().where(*filters))).scalar_one()

        query = self._worklist_order(self._base_query().where(*filters)).offset(skip).limit(limit)
        result = await db.execute(query)
        return result.scalars().all(), total

    # -----------------------------------------------------------------
    # READ — AGGREGATES
    # -----------------------------------------------------------------

    async def count_where(
        self,
        db: AsyncSession,
        *filters,
        assigned_employee_id: uuid.UUID | None = None,
    ) -> int:
        """
        Counts visible tasks matching arbitrary filter clauses, optionally scoped to one
        employee. The statistics service composes its numbers from this rather than issuing
        hand-written COUNT queries, so every statistic inherits the same soft-delete and
        deleted-lead exclusions as the lists they are supposed to summarise.
        """
        query = self._count_query().where(*filters)
        if assigned_employee_id is not None:
            query = query.where(FollowUpTask.assigned_employee_id == assigned_employee_id)
        return (await db.execute(query)).scalar_one()

    async def count_grouped_by(
        self,
        db: AsyncSession,
        column,
        assigned_employee_id: uuid.UUID | None = None,
    ) -> dict:
        """
        Returns `{column_value: count}` over visible tasks, optionally scoped to one
        employee. Used for the by-status / by-type / by-priority breakdowns.
        """
        query = (
            select(column, func.count())
            .select_from(FollowUpTask)
            .join(Lead, FollowUpTask.lead_id == Lead.id)
            .where(Lead.is_deleted == False, FollowUpTask.is_deleted == False)
            .group_by(column)
        )
        if assigned_employee_id is not None:
            query = query.where(FollowUpTask.assigned_employee_id == assigned_employee_id)

        result = await db.execute(query)
        return {row[0]: row[1] for row in result.all()}


class AdminFollowUpTaskRepository(FollowUpTaskRepository):
    """
    FollowUpTask Repository that includes soft-deleted tasks by default.
    Mirrors AdminLeadRepository in app/repositories/lead.py.
    """
    def __init__(self) -> None:
        super().__init__(include_deleted=True)
