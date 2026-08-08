"""
app/services/follow_up.py

This file implements FollowUpTaskService and FollowUpAutomationService.
Under Clean Architecture, this file belongs to the Application Business Rules (Use Cases)
layer. It contains the core business logic and orchestrates persistence via the repository.

Two services live here because they have different callers and different failure contracts:

- `FollowUpTaskService` is driven by a human through the API. Its operations validate,
  raise `AppException` subclasses on bad input, and the caller sees the error.
- `FollowUpAutomationService` is driven by *other modules* as a side effect of a domain
  event (a WhatsApp reply arrives, a lead moves to NEGOTIATION). Its operations must never
  be able to fail the event that triggered them — see `_safe_create` below for how that is
  enforced and why it is the single most important decision in this file.

Every state transition emits a `LeadActivity` through `LeadActivityService`, which remains
the sole writer of the timeline. Task lifecycle and timeline are committed in the same
transaction, so a completed task always has a matching TASK_COMPLETED entry.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.models.employee import Employee
from app.models.follow_up import (
    FollowUpTask,
    FollowUpType,
    FollowUpPriority,
    FollowUpStatus,
    CLOSED_FOLLOW_UP_STATUSES,
)
from app.models.lead import Lead, LeadStatus
from app.models.lead_activity import ActivityType
from app.repositories.follow_up import FollowUpTaskRepository
from app.repositories.lead import LeadRepository
from app.schemas.follow_up import (
    FollowUpTaskCreate,
    FollowUpTaskUpdate,
    FollowUpTaskComplete,
    FollowUpTaskReschedule,
    FollowUpTaskCancel,
)
from app.services.lead_activity import LeadActivityService


logger = logging.getLogger(__name__)


# How far ahead "upcoming" looks by default, in days. Seven days matches the planning
# horizon the sales team actually works to (this week's diary) rather than an arbitrary
# round number; the API exposes it as an overridable query parameter.
DEFAULT_UPCOMING_DAYS = 7


def _utcnow() -> datetime:
    """
    Returns the current time as a timezone-aware UTC datetime.

    Centralised so the "now" used by the worklist windows, the overdue rule and the
    statistics is obtained one way, and so tests have a single seam to reason about.
    """
    return datetime.now(timezone.utc)


def day_bounds(moment: datetime) -> tuple[datetime, datetime]:
    """
    Returns the half-open `[start_of_day, start_of_next_day)` window containing `moment`.

    Half-open, so a task due at exactly midnight belongs to exactly one day rather than
    appearing at the end of one day's list and the start of the next.

    The day is computed in UTC, which is a real limitation worth stating plainly: a team in
    IST sees "today" roll over at 05:30 local. Fixing that properly needs a configured
    business timezone, which is a settings change beyond this phase's scope; it is recorded
    as a follow-up in task.md rather than papered over with a hardcoded offset.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    start = moment.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def is_task_overdue(task: FollowUpTask, now: datetime | None = None) -> bool:
    """
    Decides whether a task is overdue, mirroring `FollowUpTaskRepository._is_overdue_clause`
    in Python so a single serialized object can be flagged without a round trip.

    These two implementations must agree. They are kept deliberately tiny and adjacent in
    intent for that reason; the test suite asserts the list endpoint and the flag never
    disagree about the same row.
    """
    if task.status in CLOSED_FOLLOW_UP_STATUSES:
        return False
    if task.status == FollowUpStatus.OVERDUE:
        return True

    reference = now or _utcnow()
    scheduled = task.scheduled_at
    if scheduled is None:
        return False
    if scheduled.tzinfo is None:
        scheduled = scheduled.replace(tzinfo=timezone.utc)
    return scheduled < reference


class FollowUpTaskService:
    """
    Service layer owning the follow-up task lifecycle: CRUD, assignment, completion,
    rescheduling, the three worklists, and statistics.

    Timeline entries are written through `LeadActivityService` rather than constructed here,
    so the shape of an activity stays defined in exactly one place.
    """

    def __init__(
        self,
        repository: FollowUpTaskRepository | None = None,
        lead_repository: LeadRepository | None = None,
        activity_service: LeadActivityService | None = None,
    ) -> None:
        self.repository = repository or FollowUpTaskRepository()
        self.lead_repository = lead_repository or LeadRepository()
        self.activity_service = activity_service or LeadActivityService()

    # -----------------------------------------------------------------
    # INTERNAL HELPERS
    # -----------------------------------------------------------------

    async def _get_lead_or_404(self, db: AsyncSession, lead_id: uuid.UUID) -> Lead:
        """
        Resolves the lead a task hangs off, rejecting unknown or soft-deleted leads.
        """
        lead = await self.lead_repository.get_by_id(db, lead_id)
        if not lead:
            raise NotFoundException(f"Lead with ID '{lead_id}' was not found.")
        return lead

    async def _validate_employee(self, db: AsyncSession, employee_id: uuid.UUID | None) -> None:
        """
        Confirms an assignee exists and is active before it is written to the FK column.

        Validated rather than trusted because assigning work to a departed or non-existent
        employee produces a task nobody will ever see — worse than a rejected request. An
        inactive employee is rejected for the same reason.
        """
        if employee_id is None:
            return

        employee = (
            await db.execute(select(Employee).where(Employee.id == employee_id))
        ).scalars().first()
        if not employee:
            raise NotFoundException(f"Employee with ID '{employee_id}' was not found.")
        if not employee.is_active:
            raise BadRequestException(
                f"Employee '{employee_id}' is inactive and cannot be assigned follow-up tasks."
            )

    @staticmethod
    def _assert_open(task: FollowUpTask, operation: str) -> None:
        """
        Guards the transitions that only make sense on an open task.

        Completing an already-completed task, or rescheduling a cancelled one, is rejected
        rather than quietly accepted: the counts this module reports are only trustworthy if
        a closed task stays closed.
        """
        if task.status in CLOSED_FOLLOW_UP_STATUSES:
            raise BadRequestException(
                f"Cannot {operation} a task that is already {task.status.value}."
            )

    @staticmethod
    def _check_version(task: FollowUpTask, expected: int | None) -> None:
        """
        Enforces optimistic locking at the service boundary, matching LeadService.

        This is the *explicit* check for a client-supplied expected version. The mapper's
        `version_id_col` still guards concurrent writes that slip past it, surfacing as a
        StaleDataError translated to 409 by the global handler.
        """
        if expected is not None and task.version != expected:
            raise ConflictException("Follow-up task was modified by another process. Please reload.")

    def _decorate(self, task: FollowUpTask, now: datetime | None = None) -> FollowUpTask:
        """
        Stamps the computed `is_overdue` flag onto an ORM instance for serialization.

        Set as a transient attribute on the instance rather than mapped to a column, because
        it is derived state that must never be persisted — storing it would create a second
        source of truth that goes stale the moment the clock moves.
        """
        # `object.__setattr__` is not needed; SQLAlchemy instances accept arbitrary
        # attributes, and an unmapped one is ignored by the flush.
        task.is_overdue = is_task_overdue(task, now)
        return task

    def _decorate_all(self, tasks: Sequence[FollowUpTask]) -> Sequence[FollowUpTask]:
        """
        Applies `_decorate` across a result set using one shared "now", so every row in a
        single response is judged against the same instant.
        """
        now = _utcnow()
        for task in tasks:
            self._decorate(task, now)
        return tasks

    # -----------------------------------------------------------------
    # CRUD
    # -----------------------------------------------------------------

    async def create_task(
        self,
        db: AsyncSession,
        schema: FollowUpTaskCreate,
    ) -> FollowUpTask:
        """
        Creates a follow-up task and emits the matching TASK_CREATED activity.

        Business Rules:
        - The lead must exist and not be soft-deleted.
        - The assignee, when supplied, must exist and be active.
        - A MEETING task additionally emits MEETING_SCHEDULED, because "when is the meeting"
          is a question asked of the timeline directly and deserves its own filterable type.
        - The task and its activity commit together, so the timeline can never disagree with
          the worklist.

        A task scheduled in the past is explicitly permitted: back-filling a follow-up that
        should have happened yesterday is a legitimate (and common) data-entry action, and
        it lands correctly on the overdue list rather than being rejected.
        """
        lead = await self._get_lead_or_404(db, schema.lead_id)
        await self._validate_employee(db, schema.assigned_employee_id)

        task = FollowUpTask(
            lead_id=lead.id,
            assigned_employee_id=schema.assigned_employee_id,
            title=schema.title,
            description=schema.description,
            follow_up_type=schema.follow_up_type,
            priority=schema.priority,
            status=FollowUpStatus.PENDING,
            scheduled_at=schema.scheduled_at,
            remarks=schema.remarks,
        )

        await self.repository.create(db, task, commit=False)
        await self._log_task_created(db, task, lead)
        await db.commit()
        await db.refresh(task)

        logger.info(
            "Created follow-up task %s (%s) for lead %s due %s.",
            task.id, task.follow_up_type.value, lead.id, task.scheduled_at,
        )
        return self._decorate(task)

    async def get_task_by_id(self, db: AsyncSession, id: uuid.UUID) -> FollowUpTask:
        """
        Retrieves a single task by ID. Raises NotFoundException if missing or soft-deleted.
        """
        task = await self.repository.get_by_id(db, id)
        if not task:
            raise NotFoundException(f"Follow-up task with ID '{id}' was not found.")
        return self._decorate(task)

    async def get_all_tasks(
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
    ) -> tuple[Sequence[FollowUpTask], int]:
        """
        Returns a filtered, paginated list of tasks, soonest-due first.
        """
        tasks, total = await self.repository.get_all(
            db,
            skip=skip,
            limit=limit,
            lead_id=lead_id,
            assigned_employee_id=assigned_employee_id,
            status=status,
            follow_up_type=follow_up_type,
            priority=priority,
            scheduled_from=scheduled_from,
            scheduled_to=scheduled_to,
            search=search,
        )
        return self._decorate_all(tasks), total

    async def update_task(
        self,
        db: AsyncSession,
        id: uuid.UUID,
        schema: FollowUpTaskUpdate,
    ) -> FollowUpTask:
        """
        Updates an open task's editable fields.

        Business Rules:
        - Optimistic locking via the optional `version` field.
        - A closed (completed/cancelled) task cannot be edited.
        - A new assignee must exist and be active.
        - Reassignment through this path emits the same TASK_ASSIGNED-style activity as the
          dedicated assign operation, so ownership changes are never invisible on the
          timeline regardless of which endpoint made them.
        - `scheduled_at` may be corrected here without emitting a TASK_RESCHEDULED entry;
          use the reschedule operation for a deliberate move. This distinction is what keeps
          "how often do we push this lead back" a countable number rather than being diluted
          by typo corrections.
        """
        task = await self.repository.get_by_id(db, id)
        if not task:
            raise NotFoundException(f"Follow-up task with ID '{id}' was not found.")

        self._check_version(task, schema.version)
        self._assert_open(task, "update")

        update_data = schema.model_dump(exclude_unset=True)
        update_data.pop("version", None)
        if not update_data:
            return self._decorate(task)

        previous_assignee = task.assigned_employee_id
        if "assigned_employee_id" in update_data:
            await self._validate_employee(db, update_data["assigned_employee_id"])

        await self.repository.update(db, db_obj=task, update_data=update_data, commit=False)

        if "assigned_employee_id" in update_data and update_data["assigned_employee_id"] != previous_assignee:
            await self._log_task_assigned(db, task, previous_assignee)

        await db.commit()
        await db.refresh(task)
        return self._decorate(task)

    async def delete_task(self, db: AsyncSession, id: uuid.UUID) -> None:
        """
        Soft deletes a task.

        No timeline entry is emitted. Deleting a task means "this was never a real piece of
        work" (a mistake, a duplicate), which is a correction rather than a lead
        interaction. The deletion is still fully captured by the automatic audit-log
        listener, which is the right place for that level of detail. Cancelling — the
        operation that *does* say something about the lead — is what writes to the timeline.
        """
        task = await self.repository.get_by_id(db, id)
        if not task:
            raise NotFoundException(f"Follow-up task with ID '{id}' was not found.")

        await self.repository.delete(db, db_obj=task)
        logger.info("Soft-deleted follow-up task %s.", id)

    # -----------------------------------------------------------------
    # LIFECYCLE TRANSITIONS
    # -----------------------------------------------------------------

    async def assign_task(
        self,
        db: AsyncSession,
        id: uuid.UUID,
        assigned_employee_id: uuid.UUID | None,
    ) -> FollowUpTask:
        """
        Assigns (or, with a null id, unassigns) a task's owner and records it on the
        timeline.
        """
        task = await self.repository.get_by_id(db, id)
        if not task:
            raise NotFoundException(f"Follow-up task with ID '{id}' was not found.")

        self._assert_open(task, "reassign")
        await self._validate_employee(db, assigned_employee_id)

        previous = task.assigned_employee_id
        if previous == assigned_employee_id:
            # A no-op assignment writes nothing rather than appending an empty timeline
            # entry claiming an ownership change that did not happen.
            return self._decorate(task)

        await self.repository.update(
            db, db_obj=task,
            update_data={"assigned_employee_id": assigned_employee_id},
            commit=False,
        )
        await self._log_task_assigned(db, task, previous)
        await db.commit()
        await db.refresh(task)

        logger.info("Assigned follow-up task %s to employee %s.", task.id, assigned_employee_id)
        return self._decorate(task)

    async def complete_task(
        self,
        db: AsyncSession,
        id: uuid.UUID,
        schema: FollowUpTaskComplete | None = None,
    ) -> FollowUpTask:
        """
        Marks a task complete and emits the matching activity.

        Business Rules:
        - Only an open task can be completed.
        - `completed_at` defaults to now; a caller may supply the real completion time when
          logging work after the fact.
        - The emitted activity type depends on the task's channel: a completed CALL writes
          PHONE_CALL, everything else writes TASK_COMPLETED. This is what makes "show me
          every call we made" a real query on the timeline rather than a metadata scan.
        - Supplied remarks overwrite the task's remarks, since the outcome of the work is
          more useful than the instruction that preceded it. The instruction survives in the
          audit log and in the TASK_CREATED activity's description.
        """
        task = await self.repository.get_by_id(db, id)
        if not task:
            raise NotFoundException(f"Follow-up task with ID '{id}' was not found.")

        self._assert_open(task, "complete")

        completed_at = (schema.completed_at if schema else None) or _utcnow()
        remarks = schema.remarks if schema else None

        update_data: dict[str, Any] = {
            "status": FollowUpStatus.COMPLETED,
            "completed_at": completed_at,
        }
        if remarks is not None:
            update_data["remarks"] = remarks

        await self.repository.update(db, db_obj=task, update_data=update_data, commit=False)
        await self._log_task_completed(db, task, remarks)
        await db.commit()
        await db.refresh(task)

        logger.info("Completed follow-up task %s at %s.", task.id, completed_at)
        return self._decorate(task)

    async def reschedule_task(
        self,
        db: AsyncSession,
        id: uuid.UUID,
        schema: FollowUpTaskReschedule,
    ) -> FollowUpTask:
        """
        Moves a task to a new due time and emits a TASK_RESCHEDULED activity carrying both
        the old and the new time.

        Business Rules:
        - Only an open task can be rescheduled.
        - Rescheduling to the same instant is rejected: it records a decision that was not
          made, and would inflate the "how many times has this lead been pushed back" signal
          the activity type exists to provide.
        - A task that had escalated to OVERDUE returns to PENDING, because it now has a
          fresh due date and is no longer late against it.
        """
        task = await self.repository.get_by_id(db, id)
        if not task:
            raise NotFoundException(f"Follow-up task with ID '{id}' was not found.")

        self._assert_open(task, "reschedule")

        old_scheduled_at = task.scheduled_at
        if old_scheduled_at is not None and old_scheduled_at.tzinfo is None:
            old_scheduled_at = old_scheduled_at.replace(tzinfo=timezone.utc)

        if old_scheduled_at == schema.scheduled_at:
            raise BadRequestException(
                "The task is already scheduled for that time; nothing to reschedule."
            )

        update_data: dict[str, Any] = {
            "scheduled_at": schema.scheduled_at,
            # A rescheduled task is no longer late against its new date.
            "status": FollowUpStatus.PENDING,
        }
        if schema.remarks is not None:
            update_data["remarks"] = schema.remarks

        await self.repository.update(db, db_obj=task, update_data=update_data, commit=False)
        await self._log_task_rescheduled(db, task, old_scheduled_at, schema.scheduled_at, schema.remarks)
        await db.commit()
        await db.refresh(task)

        logger.info(
            "Rescheduled follow-up task %s from %s to %s.",
            task.id, old_scheduled_at, schema.scheduled_at,
        )
        return self._decorate(task)

    async def cancel_task(
        self,
        db: AsyncSession,
        id: uuid.UUID,
        schema: FollowUpTaskCancel | None = None,
    ) -> FollowUpTask:
        """
        Cancels a task and emits a TASK_CANCELLED activity.

        Cancelling is distinct from deleting: it means "we decided not to do this", which is
        a real fact about the lead and belongs on the timeline. Deleting means the task
        should never have existed.
        """
        task = await self.repository.get_by_id(db, id)
        if not task:
            raise NotFoundException(f"Follow-up task with ID '{id}' was not found.")

        self._assert_open(task, "cancel")

        remarks = schema.remarks if schema else None
        update_data: dict[str, Any] = {"status": FollowUpStatus.CANCELLED}
        if remarks is not None:
            update_data["remarks"] = remarks

        await self.repository.update(db, db_obj=task, update_data=update_data, commit=False)
        await self._log_task_cancelled(db, task, remarks)
        await db.commit()
        await db.refresh(task)

        logger.info("Cancelled follow-up task %s.", task.id)
        return self._decorate(task)

    # -----------------------------------------------------------------
    # WORKLISTS
    # -----------------------------------------------------------------

    async def get_todays_tasks(
        self,
        db: AsyncSession,
        assigned_employee_id: uuid.UUID | None = None,
        skip: int = 0,
        limit: int = 50,
        now: datetime | None = None,
    ) -> tuple[Sequence[FollowUpTask], int]:
        """
        Returns open tasks due at any point today, soonest first.

        Scoped strictly to today's window: a task that was due yesterday and is now overdue
        appears on the overdue list, not here. Conflating the two would hide the distinction
        between "planned for today" and "already late", which is the distinction that makes
        the overdue list worth looking at.
        """
        reference = now or _utcnow()
        start, end = day_bounds(reference)
        tasks, total = await self.repository.get_due_between(
            db, start=start, end=end,
            assigned_employee_id=assigned_employee_id,
            skip=skip, limit=limit,
        )
        return self._decorate_all(tasks), total

    async def get_upcoming_tasks(
        self,
        db: AsyncSession,
        assigned_employee_id: uuid.UUID | None = None,
        days: int = DEFAULT_UPCOMING_DAYS,
        skip: int = 0,
        limit: int = 50,
        now: datetime | None = None,
    ) -> tuple[Sequence[FollowUpTask], int]:
        """
        Returns open tasks due from tomorrow through the next `days` days.

        Starts at tomorrow rather than at "now" so "today" and "upcoming" partition the
        near-term worklist instead of overlapping — a task due this afternoon should appear
        on exactly one of the two lists.
        """
        if days < 1:
            raise BadRequestException("The upcoming window must be at least 1 day.")

        reference = now or _utcnow()
        _, tomorrow = day_bounds(reference)
        end = tomorrow + timedelta(days=days)

        tasks, total = await self.repository.get_due_between(
            db, start=tomorrow, end=end,
            assigned_employee_id=assigned_employee_id,
            skip=skip, limit=limit,
        )
        return self._decorate_all(tasks), total

    async def get_overdue_tasks(
        self,
        db: AsyncSession,
        assigned_employee_id: uuid.UUID | None = None,
        skip: int = 0,
        limit: int = 50,
        now: datetime | None = None,
    ) -> tuple[Sequence[FollowUpTask], int]:
        """
        Returns open tasks whose due time has passed, longest-overdue first.
        """
        reference = now or _utcnow()
        tasks, total = await self.repository.get_overdue(
            db, now=reference,
            assigned_employee_id=assigned_employee_id,
            skip=skip, limit=limit,
        )
        return self._decorate_all(tasks), total

    # -----------------------------------------------------------------
    # STATISTICS
    # -----------------------------------------------------------------

    async def get_statistics(
        self,
        db: AsyncSession,
        assigned_employee_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Builds the follow-up summary, optionally scoped to one employee.

        Every number is derived through the repository's filtered count helpers, so the
        statistics inherit exactly the same soft-delete and deleted-lead exclusions as the
        lists they summarise. A dashboard that disagrees with the list it links to is worse
        than no dashboard.

        `pending` deliberately excludes overdue work so the three headline numbers
        (pending / overdue / completed) partition cleanly and can be read as a breakdown
        rather than as overlapping sets.
        """
        reference = now or _utcnow()
        start_today, tomorrow = day_bounds(reference)
        week_end = tomorrow + timedelta(days=DEFAULT_UPCOMING_DAYS)

        overdue_clause = self.repository._is_overdue_clause(reference)

        total = await self.repository.count_where(
            db, assigned_employee_id=assigned_employee_id
        )
        completed = await self.repository.count_where(
            db, FollowUpTask.status == FollowUpStatus.COMPLETED,
            assigned_employee_id=assigned_employee_id,
        )
        cancelled = await self.repository.count_where(
            db, FollowUpTask.status == FollowUpStatus.CANCELLED,
            assigned_employee_id=assigned_employee_id,
        )
        overdue = await self.repository.count_where(
            db, overdue_clause, assigned_employee_id=assigned_employee_id
        )
        # Open work that is not yet late.
        pending = await self.repository.count_where(
            db,
            FollowUpTask.status == FollowUpStatus.PENDING,
            FollowUpTask.scheduled_at >= reference,
            assigned_employee_id=assigned_employee_id,
        )
        due_today = await self.repository.count_where(
            db,
            FollowUpTask.status.in_([FollowUpStatus.PENDING, FollowUpStatus.OVERDUE]),
            FollowUpTask.scheduled_at >= start_today,
            FollowUpTask.scheduled_at < tomorrow,
            assigned_employee_id=assigned_employee_id,
        )
        due_this_week = await self.repository.count_where(
            db,
            FollowUpTask.status.in_([FollowUpStatus.PENDING, FollowUpStatus.OVERDUE]),
            FollowUpTask.scheduled_at >= start_today,
            FollowUpTask.scheduled_at < week_end,
            assigned_employee_id=assigned_employee_id,
        )

        by_status = await self.repository.count_grouped_by(
            db, FollowUpTask.status, assigned_employee_id=assigned_employee_id
        )
        by_type = await self.repository.count_grouped_by(
            db, FollowUpTask.follow_up_type, assigned_employee_id=assigned_employee_id
        )
        by_priority = await self.repository.count_grouped_by(
            db, FollowUpTask.priority, assigned_employee_id=assigned_employee_id
        )

        # Completion rate over *resolved* work only. Dividing by `total` instead would let a
        # large backlog of future tasks drag the number down and make a productive team look
        # idle, which would make the metric useless for the thing it is meant to measure.
        resolved = completed + cancelled
        completion_rate = round((completed / resolved) * 100, 2) if resolved else 0.0

        def _key(value) -> str:
            return value.value if hasattr(value, "value") else str(value)

        return {
            "total": total,
            "pending": pending,
            "completed": completed,
            "cancelled": cancelled,
            "overdue": overdue,
            "due_today": due_today,
            "due_this_week": due_this_week,
            "completion_rate": completion_rate,
            "by_status": {_key(k): v for k, v in by_status.items()},
            "by_type": {_key(k): v for k, v in by_type.items()},
            "by_priority": {_key(k): v for k, v in by_priority.items()},
            "assigned_employee_id": assigned_employee_id,
        }

    # -----------------------------------------------------------------
    # TIMELINE HOOKS
    # Each transition gets its own entry so the timeline is filterable by what happened.
    # -----------------------------------------------------------------

    def _task_metadata(self, task: FollowUpTask, **extra: Any) -> dict[str, Any]:
        """
        Builds the common machine-readable payload attached to every task activity, so the
        frontend can link a timeline entry back to the live task from any of them.
        """
        payload: dict[str, Any] = {
            "task_id": str(task.id),
            "follow_up_type": task.follow_up_type.value if task.follow_up_type else None,
            "priority": task.priority.value if task.priority else None,
            "status": task.status.value if task.status else None,
            "scheduled_at": task.scheduled_at.isoformat() if task.scheduled_at else None,
            "assigned_employee_id": (
                str(task.assigned_employee_id) if task.assigned_employee_id else None
            ),
        }
        payload.update(extra)
        return payload

    async def _log_task_created(
        self,
        db: AsyncSession,
        task: FollowUpTask,
        lead: Lead,
        automated: bool = False,
        trigger: str | None = None,
    ) -> None:
        """
        Records that a follow-up was scheduled. A MEETING additionally gets its own
        MEETING_SCHEDULED entry, which the specification calls for explicitly and which
        makes "what meetings are booked" answerable from the timeline alone.
        """
        due = task.scheduled_at.isoformat() if task.scheduled_at else "an unspecified time"
        await self.activity_service.record(
            db,
            lead_id=task.lead_id,
            activity_type=ActivityType.TASK_CREATED,
            title=f"Follow-up task created: {task.title}",
            description=(
                f"A {task.follow_up_type.value} follow-up was scheduled for {due} "
                f"with {task.priority.value} priority."
            ),
            metadata=self._task_metadata(task, automated=automated, trigger=trigger),
            commit=False,
        )

        if task.follow_up_type == FollowUpType.MEETING:
            await self.activity_service.record(
                db,
                lead_id=task.lead_id,
                activity_type=ActivityType.MEETING_SCHEDULED,
                title=f"Meeting scheduled: {task.title}",
                description=f"A meeting with {lead.business_name} was scheduled for {due}.",
                metadata=self._task_metadata(task, automated=automated, trigger=trigger),
                commit=False,
            )

    async def _log_task_completed(
        self,
        db: AsyncSession,
        task: FollowUpTask,
        remarks: str | None,
    ) -> None:
        """
        Records that a follow-up was carried out. A completed CALL is recorded as a
        PHONE_CALL, which is the domain event that actually occurred; the generic
        TASK_COMPLETED covers every other channel.
        """
        is_call = task.follow_up_type == FollowUpType.CALL
        activity_type = ActivityType.PHONE_CALL if is_call else ActivityType.TASK_COMPLETED
        title = "Call completed" if is_call else f"Follow-up completed: {task.title}"

        description = remarks or f"The {task.follow_up_type.value} follow-up '{task.title}' was completed."
        await self.activity_service.record(
            db,
            lead_id=task.lead_id,
            activity_type=activity_type,
            title=title,
            description=description,
            metadata=self._task_metadata(
                task,
                completed_at=task.completed_at.isoformat() if task.completed_at else None,
                remarks=remarks,
            ),
            commit=False,
        )

    async def _log_task_rescheduled(
        self,
        db: AsyncSession,
        task: FollowUpTask,
        old_scheduled_at: datetime | None,
        new_scheduled_at: datetime,
        remarks: str | None,
    ) -> None:
        """
        Records a deliberate move of a follow-up, carrying both times so "how far was this
        pushed" is answerable without reading the audit log.
        """
        old_iso = old_scheduled_at.isoformat() if old_scheduled_at else None
        await self.activity_service.record(
            db,
            lead_id=task.lead_id,
            activity_type=ActivityType.TASK_RESCHEDULED,
            title=f"Follow-up rescheduled: {task.title}",
            description=(
                f"The follow-up was moved from {old_iso} to {new_scheduled_at.isoformat()}."
                + (f" Reason: {remarks}" if remarks else "")
            ),
            metadata=self._task_metadata(
                task,
                old_scheduled_at=old_iso,
                new_scheduled_at=new_scheduled_at.isoformat(),
                remarks=remarks,
            ),
            commit=False,
        )

    async def _log_task_cancelled(
        self,
        db: AsyncSession,
        task: FollowUpTask,
        remarks: str | None,
    ) -> None:
        """
        Records that a planned follow-up was abandoned.
        """
        await self.activity_service.record(
            db,
            lead_id=task.lead_id,
            activity_type=ActivityType.TASK_CANCELLED,
            title=f"Follow-up cancelled: {task.title}",
            description=remarks or f"The follow-up '{task.title}' was cancelled.",
            metadata=self._task_metadata(task, remarks=remarks),
            commit=False,
        )

    async def _log_task_assigned(
        self,
        db: AsyncSession,
        task: FollowUpTask,
        previous_employee_id: uuid.UUID | None,
    ) -> None:
        """
        Records an ownership change. Uses the generic FOLLOW_UP type rather than a dedicated
        one: reassignment is internal workload management rather than an interaction with
        the lead, so it belongs on the timeline for accountability but does not warrant its
        own filterable category alongside the four task lifecycle events.
        """
        new_id = task.assigned_employee_id
        await self.activity_service.record(
            db,
            lead_id=task.lead_id,
            activity_type=ActivityType.FOLLOW_UP,
            title=(
                f"Follow-up reassigned: {task.title}" if new_id
                else f"Follow-up unassigned: {task.title}"
            ),
            description=(
                f"Ownership of the follow-up moved from {previous_employee_id} to {new_id}."
                if new_id else
                f"The follow-up '{task.title}' no longer has an assigned owner."
            ),
            metadata=self._task_metadata(
                task,
                previous_employee_id=str(previous_employee_id) if previous_employee_id else None,
                new_employee_id=str(new_id) if new_id else None,
            ),
            commit=False,
        )


class FollowUpAutomationService:
    """
    Creates follow-up tasks automatically in response to domain events elsewhere in the CRM.

    The specification names four triggers:
    - a lead replies "Interested"
    - a lead replies "Need Details"
    - a lead's status becomes NEGOTIATION
    - a campaign reply indicates manual contact is required

    All four are expressed as data in `AUTOMATION_RULES` rather than as branching, so the
    whole policy is readable at a glance and a new trigger is a dictionary entry rather than
    a new code path.

    **The contract that matters:** an automation failure must never fail the event that
    triggered it. If recording a WhatsApp reply succeeded but creating its follow-up task
    raised, the correct outcome is a recorded reply and a logged error — not a 500 that
    loses the reply. `_safe_create` enforces that, and the reasoning is spelled out there
    because it is the kind of decision that looks like sloppy error handling until you know
    why it was made.
    """

    def __init__(
        self,
        repository: FollowUpTaskRepository | None = None,
        lead_repository: LeadRepository | None = None,
        activity_service: LeadActivityService | None = None,
        task_service: FollowUpTaskService | None = None,
    ) -> None:
        self.repository = repository or FollowUpTaskRepository()
        self.lead_repository = lead_repository or LeadRepository()
        self.activity_service = activity_service or LeadActivityService()
        self.task_service = task_service or FollowUpTaskService(
            repository=self.repository,
            lead_repository=self.lead_repository,
            activity_service=self.activity_service,
        )

    # Trigger policy. Each entry says: what task to raise, how urgent, and how soon.
    #
    # The delays encode real sales practice rather than round numbers. An "interested"
    # reply gets a 2-hour call window because responding the same session is what converts;
    # "need details" gets 4 hours because it needs material prepared first; NEGOTIATION gets
    # a next-morning meeting slot because it is a scheduled conversation, not a callback;
    # and an unclassifiable reply gets a 1-hour window because a human has to read it before
    # anything else can be decided.
    AUTOMATION_RULES: dict[str, dict[str, Any]] = {
        "reply_interested": {
            "follow_up_type": FollowUpType.CALL,
            "priority": FollowUpPriority.HIGH,
            "delay_hours": 2,
            "title": "Call interested lead",
            "description": "The lead replied that they are interested. Call them to qualify and quote.",
        },
        "reply_need_details": {
            "follow_up_type": FollowUpType.WHATSAPP,
            "priority": FollowUpPriority.MEDIUM,
            "delay_hours": 4,
            "title": "Send requested details",
            "description": "The lead asked for more details. Send pricing, packages and samples.",
        },
        "status_negotiation": {
            "follow_up_type": FollowUpType.MEETING,
            "priority": FollowUpPriority.URGENT,
            "delay_hours": 24,
            "title": "Negotiation meeting",
            "description": "The lead entered negotiation. Schedule and hold the pricing discussion.",
        },
        "manual_contact_required": {
            "follow_up_type": FollowUpType.CALL,
            "priority": FollowUpPriority.HIGH,
            "delay_hours": 1,
            "title": "Review campaign reply",
            "description": "The lead replied to a campaign in a way that needs a human to read and respond.",
        },
    }

    # Reply classifications that map onto a trigger. Keys are matched case-insensitively
    # against the `reply_type` supplied by the WhatsApp module, whose own vocabulary
    # ("interested" / "need_details" / "not_interested") is defined in
    # `app/services/whatsapp.py::REPLY_TYPE_TO_LEAD_STATUS`.
    #
    # "not_interested" is deliberately absent: a lead who said no should not generate a task
    # nagging someone to call them back. An *unrecognised* reply type is a different case —
    # it means nobody has classified the message, so it routes to manual_contact_required.
    REPLY_TYPE_TRIGGERS: dict[str, str] = {
        "interested": "reply_interested",
        "need_details": "reply_need_details",
        "not_interested": "",  # explicitly no task
    }

    async def _safe_create(
        self,
        db: AsyncSession,
        lead: Lead,
        trigger: str,
        commit: bool,
    ) -> FollowUpTask | None:
        """
        Creates the task a trigger calls for, isolating and swallowing any failure.

        Automation runs as a side effect of a domain event that has already been accepted —
        a reply was received, a status was changed. Letting a follow-up failure propagate
        would roll back that primary event, which means a provider webhook we cannot replay
        would be lost because of a secondary convenience feature.

        Catching the exception is necessary but **not sufficient**, and this is the subtle
        part. A database-level error (an FK violation, a constraint breach) poisons the
        whole SQLAlchemy session: the transaction enters an aborted state, and the caller's
        own subsequent `db.commit()` fails with `PendingRollbackError` even though we
        returned quietly. Swallowing alone would therefore still destroy the very event it
        was written to protect.

        So the work runs inside a SAVEPOINT (`db.begin_nested()`). A failure rolls back to
        the savepoint, discarding only the automation's writes and leaving the enclosing
        transaction clean and committable. That is what actually delivers the contract this
        method claims.

        Broad `except Exception` is deliberate and is the point of the method, not an
        oversight. It is confined to this one function so no other code path in the module
        silently swallows errors.
        """
        rule = self.AUTOMATION_RULES.get(trigger)
        if not rule:
            logger.warning("Unknown follow-up automation trigger '%s'; no task created.", trigger)
            return None

        task: FollowUpTask | None = None
        try:
            follow_up_type: FollowUpType = rule["follow_up_type"]

            # De-duplicate: a lead that replies three times in an afternoon should end up
            # with one open call task, not three. Scoped to open tasks of the same type, so
            # a genuine new follow-up after the last one was completed still gets created.
            existing = await self.repository.find_open_duplicate(
                db, lead_id=lead.id, follow_up_type=follow_up_type
            )
            if existing:
                logger.info(
                    "Skipped automated follow-up for lead %s (trigger '%s'): open %s task %s already exists.",
                    lead.id, trigger, follow_up_type.value, existing.id,
                )
                return None

            # The SAVEPOINT. Everything inside is atomic and independently revertible.
            async with db.begin_nested():
                task = FollowUpTask(
                    lead_id=lead.id,
                    # Inherit the lead's owner so automated work lands on the right desk
                    # immediately. An unowned lead produces an unassigned task, which is
                    # correct: it surfaces on the unfiltered worklist for a manager to
                    # route, rather than being invented onto an arbitrary employee.
                    assigned_employee_id=lead.assigned_employee_id,
                    title=rule["title"],
                    description=rule["description"],
                    follow_up_type=follow_up_type,
                    priority=rule["priority"],
                    status=FollowUpStatus.PENDING,
                    scheduled_at=_utcnow() + timedelta(hours=rule["delay_hours"]),
                )

                await self.repository.create(db, task, commit=False)
                await self.task_service._log_task_created(
                    db, task, lead, automated=True, trigger=trigger
                )
            # Exiting the context manager releases the savepoint; the writes are now part of
            # the enclosing transaction and commit (or roll back) with the domain event.

        except Exception as exc:
            # See the docstring: the triggering domain event must survive this, both
            # logically (no re-raise) and mechanically (the savepoint rollback above has
            # already left the session usable).
            logger.error(
                "Follow-up automation failed for lead %s on trigger '%s': %s",
                lead.id, trigger, exc, exc_info=True,
            )
            return None

        if commit:
            await db.commit()
            await db.refresh(task)

        logger.info(
            "Automation trigger '%s' created follow-up task %s for lead %s due %s.",
            trigger, task.id, lead.id, task.scheduled_at,
        )
        return task

    async def on_campaign_reply(
        self,
        db: AsyncSession,
        lead: Lead,
        reply_type: str | None,
        commit: bool = False,
    ) -> FollowUpTask | None:
        """
        Handles a lead's reply to a WhatsApp campaign.

        Called by `CampaignReplyService.record_reply` with `commit=False`, so the task joins
        the same transaction as the reply itself and the two can never disagree.

        Routing:
        - a classified "interested" / "need_details" reply raises its specific task;
        - a classified "not_interested" reply raises nothing;
        - anything else — including an unclassified (`None`) reply — routes to
          `manual_contact_required`, because a message nobody has read is precisely the case
          that needs a human. Defaulting to "no task" here would let real replies fall
          silently on the floor, which is the failure this module exists to prevent.
        """
        key = (reply_type or "").strip().lower()

        if key in self.REPLY_TYPE_TRIGGERS:
            trigger = self.REPLY_TYPE_TRIGGERS[key]
            if not trigger:
                logger.info(
                    "Reply type '%s' on lead %s intentionally creates no follow-up task.",
                    key, lead.id,
                )
                return None
        else:
            trigger = "manual_contact_required"

        return await self._safe_create(db, lead, trigger, commit=commit)

    async def on_lead_status_changed(
        self,
        db: AsyncSession,
        lead: Lead,
        old_status: LeadStatus | None,
        new_status: LeadStatus | None,
        commit: bool = False,
    ) -> FollowUpTask | None:
        """
        Handles a lead's CRM status transition.

        Only NEGOTIATION raises a task, and only on the *transition into* it — re-saving a
        lead that is already in negotiation must not stack up meeting tasks. That is why
        both the old and the new status are required here rather than just the new one.
        """
        if new_status != LeadStatus.NEGOTIATION or old_status == LeadStatus.NEGOTIATION:
            return None

        return await self._safe_create(db, lead, "status_negotiation", commit=commit)
