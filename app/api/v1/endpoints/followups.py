"""
app/api/v1/endpoints/followups.py

This file defines the API routes (Endpoints) for the Follow-up & Task Management module.
Under Clean Architecture, this file resides in the Interface Adapters layer.
It acts as the HTTP controller: parsing requests, delegating execution to the Service layer,
and returning structured JSON responses matching our Pydantic schemas.

**Route ordering is load-bearing.** The literal paths `/followups/today`, `/followups/upcoming`,
`/followups/overdue` and `/followups/statistics` are declared BEFORE `/followups/{id}`.
FastAPI matches routes in declaration order, so with the parameterised route first, a request
for `/followups/today` would bind `id="today"` and fail UUID validation with a 422. This is the
same hazard `lead_imports.py` documents for `/leads/import`, solved the same way.

RBAC: reads require `followups:view`, creation `followups:create`, every mutation and
lifecycle transition `followups:update`, and deletion `followups:delete`. These are new
permissions rather than a reuse of `leads:*`, because working a follow-up queue and editing
the lead records themselves are different capabilities: a junior caller should be able to
complete their tasks without being able to rewrite lead data.
"""

import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_follow_up_task_service, RequirePermission
from app.models.follow_up import FollowUpType, FollowUpPriority, FollowUpStatus
from app.schemas.follow_up import (
    FollowUpTaskCreate,
    FollowUpTaskUpdate,
    FollowUpTaskComplete,
    FollowUpTaskReschedule,
    FollowUpTaskAssign,
    FollowUpTaskCancel,
    FollowUpTaskResponse,
    FollowUpTaskListResponse,
    FollowUpStatisticsResponse,
)
from app.services.follow_up import FollowUpTaskService, DEFAULT_UPCOMING_DAYS

router = APIRouter()


# =====================================================================
# WORKLISTS & STATISTICS
# Declared before /{id} — see the module docstring.
# =====================================================================

@router.get(
    "/today",
    response_model=FollowUpTaskListResponse,
    status_code=status.HTTP_200_OK,
    summary="Today's follow-ups",
    description=(
        "Fetches open follow-up tasks due at some point today (UTC day boundaries), soonest first. "
        "Tasks that were due on an earlier day appear on /followups/overdue instead, not here."
    ),
    dependencies=[Depends(RequirePermission("followups:view"))],
)
async def get_todays_followups(
    assigned_employee_id: uuid.UUID | None = Query(None, description="Scope to one employee's worklist"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    service: FollowUpTaskService = Depends(get_follow_up_task_service),
) -> FollowUpTaskListResponse:
    """
    GET /followups/today Endpoint Flow:
    Service computes today's window -> Repository -> paginated soonest-first worklist + total.
    """
    items, total = await service.get_todays_tasks(
        db=db, assigned_employee_id=assigned_employee_id, skip=skip, limit=limit
    )
    return FollowUpTaskListResponse(items=items, total=total, skip=skip, limit=limit)


@router.get(
    "/upcoming",
    response_model=FollowUpTaskListResponse,
    status_code=status.HTTP_200_OK,
    summary="Upcoming follow-ups",
    description=(
        "Fetches open follow-up tasks due from tomorrow through the next `days` days, soonest first. "
        "Starts at tomorrow so that /followups/today and /followups/upcoming partition the near-term "
        "worklist rather than overlapping."
    ),
    dependencies=[Depends(RequirePermission("followups:view"))],
)
async def get_upcoming_followups(
    days: int = Query(DEFAULT_UPCOMING_DAYS, ge=1, le=365, description="How many days ahead to look"),
    assigned_employee_id: uuid.UUID | None = Query(None, description="Scope to one employee's worklist"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    service: FollowUpTaskService = Depends(get_follow_up_task_service),
) -> FollowUpTaskListResponse:
    """
    GET /followups/upcoming Endpoint Flow:
    Service computes the forward window -> Repository -> paginated worklist + total.
    """
    items, total = await service.get_upcoming_tasks(
        db=db, assigned_employee_id=assigned_employee_id, days=days, skip=skip, limit=limit
    )
    return FollowUpTaskListResponse(items=items, total=total, skip=skip, limit=limit)


@router.get(
    "/overdue",
    response_model=FollowUpTaskListResponse,
    status_code=status.HTTP_200_OK,
    summary="Overdue follow-ups",
    description=(
        "Fetches open follow-up tasks whose due time has passed, longest-overdue first. "
        "A task counts as overdue when its stored status is OVERDUE, or when it is still PENDING "
        "and its scheduled time is in the past — so the list is correct even though this phase "
        "ships no background sweeper."
    ),
    dependencies=[Depends(RequirePermission("followups:view"))],
)
async def get_overdue_followups(
    assigned_employee_id: uuid.UUID | None = Query(None, description="Scope to one employee's worklist"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    service: FollowUpTaskService = Depends(get_follow_up_task_service),
) -> FollowUpTaskListResponse:
    """
    GET /followups/overdue Endpoint Flow:
    Service applies the derived-overdue rule -> Repository -> paginated oldest-first worklist.
    """
    items, total = await service.get_overdue_tasks(
        db=db, assigned_employee_id=assigned_employee_id, skip=skip, limit=limit
    )
    return FollowUpTaskListResponse(items=items, total=total, skip=skip, limit=limit)


@router.get(
    "/statistics",
    response_model=FollowUpStatisticsResponse,
    status_code=status.HTTP_200_OK,
    summary="Follow-up statistics",
    description=(
        "Returns headline follow-up counters (total/pending/completed/cancelled/overdue/due today/"
        "due this week), a completion rate over resolved tasks, and breakdowns by status, type and "
        "priority. Optionally scoped to one employee."
    ),
    dependencies=[Depends(RequirePermission("followups:view"))],
)
async def get_followup_statistics(
    assigned_employee_id: uuid.UUID | None = Query(None, description="Scope the statistics to one employee"),
    db: AsyncSession = Depends(get_db),
    service: FollowUpTaskService = Depends(get_follow_up_task_service),
) -> FollowUpStatisticsResponse:
    """
    GET /followups/statistics Endpoint Flow:
    Service composes every counter through the same filtered repository helpers the lists use,
    so the summary and the lists can never disagree.
    """
    stats = await service.get_statistics(db=db, assigned_employee_id=assigned_employee_id)
    return FollowUpStatisticsResponse(**stats)


# =====================================================================
# CRUD
# =====================================================================

@router.get(
    "",
    response_model=FollowUpTaskListResponse,
    status_code=status.HTTP_200_OK,
    summary="List follow-up tasks",
    description=(
        "Fetches a filtered, paginated list of follow-up tasks ordered soonest-due first, then by "
        "descending priority. Tasks belonging to soft-deleted leads are never returned."
    ),
    dependencies=[Depends(RequirePermission("followups:view"))],
)
async def get_followups(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    lead_id: uuid.UUID | None = Query(None, description="Only tasks about this lead"),
    assigned_employee_id: uuid.UUID | None = Query(None, description="Only tasks owned by this employee"),
    task_status: FollowUpStatus | None = Query(None, alias="status", description="Filter by lifecycle status"),
    follow_up_type: FollowUpType | None = Query(None, description="Filter by channel"),
    priority: FollowUpPriority | None = Query(None, description="Filter by priority"),
    scheduled_from: datetime | None = Query(None, description="Only tasks due at or after this time"),
    scheduled_to: datetime | None = Query(None, description="Only tasks due strictly before this time"),
    search: str | None = Query(None, description="Case-insensitive match on title or description"),
    db: AsyncSession = Depends(get_db),
    service: FollowUpTaskService = Depends(get_follow_up_task_service),
) -> FollowUpTaskListResponse:
    """
    GET /followups Endpoint Flow:
    Query params -> Service -> Repository -> paginated task list + total count.

    `status` is received into `task_status` via an alias, because `status` is also the name
    of the imported FastAPI module used for the HTTP status constants in this file.
    """
    items, total = await service.get_all_tasks(
        db=db,
        skip=skip,
        limit=limit,
        lead_id=lead_id,
        assigned_employee_id=assigned_employee_id,
        status=task_status,
        follow_up_type=follow_up_type,
        priority=priority,
        scheduled_from=scheduled_from,
        scheduled_to=scheduled_to,
        search=search,
    )
    return FollowUpTaskListResponse(items=items, total=total, skip=skip, limit=limit)


@router.post(
    "",
    response_model=FollowUpTaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a follow-up task",
    description=(
        "Creates a follow-up task against a lead and appends a TASK_CREATED entry to that lead's "
        "activity timeline (plus MEETING_SCHEDULED when the type is MEETING). Raises 404 if the "
        "lead or the assignee does not exist, and 400 if the assignee is inactive."
    ),
    dependencies=[Depends(RequirePermission("followups:create"))],
)
async def create_followup(
    schema: FollowUpTaskCreate,
    db: AsyncSession = Depends(get_db),
    service: FollowUpTaskService = Depends(get_follow_up_task_service),
) -> FollowUpTaskResponse:
    """
    POST /followups Endpoint Flow:
    Client JSON -> Validation -> Service (task + activity in one transaction) -> created task.
    """
    return await service.create_task(db=db, schema=schema)


@router.get(
    "/{id}",
    response_model=FollowUpTaskResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a follow-up task",
    description="Fetches a single follow-up task by ID. Raises 404 if it does not exist or was deleted.",
    dependencies=[Depends(RequirePermission("followups:view"))],
)
async def get_followup(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: FollowUpTaskService = Depends(get_follow_up_task_service),
) -> FollowUpTaskResponse:
    """
    GET /followups/{id} Endpoint Flow:
    Service -> Repository -> single task, with the computed is_overdue flag applied.
    """
    return await service.get_task_by_id(db=db, id=id)


@router.put(
    "/{id}",
    response_model=FollowUpTaskResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a follow-up task",
    description=(
        "Updates an open task's editable fields. Status is deliberately not settable here — use the "
        "complete/reschedule/cancel operations, which enforce their own preconditions and write the "
        "matching timeline entries. Raises 409 on a version conflict and 400 on a closed task."
    ),
    dependencies=[Depends(RequirePermission("followups:update"))],
)
async def update_followup(
    id: uuid.UUID,
    schema: FollowUpTaskUpdate,
    db: AsyncSession = Depends(get_db),
    service: FollowUpTaskService = Depends(get_follow_up_task_service),
) -> FollowUpTaskResponse:
    """
    PUT /followups/{id} Endpoint Flow:
    Validates version + open state -> Service -> updated task.
    """
    return await service.update_task(db=db, id=id, schema=schema)


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a follow-up task",
    description=(
        "Soft deletes a follow-up task. No timeline entry is written: deletion means the task should "
        "never have existed, which is a correction rather than a lead interaction (the audit log still "
        "records it). To record a deliberate decision not to do the work, cancel the task instead."
    ),
    dependencies=[Depends(RequirePermission("followups:delete"))],
)
async def delete_followup(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: FollowUpTaskService = Depends(get_follow_up_task_service),
) -> None:
    """
    DELETE /followups/{id} Endpoint Flow:
    Soft deletes the task. Raises 404 if not found.
    """
    await service.delete_task(db=db, id=id)


# =====================================================================
# LIFECYCLE TRANSITIONS
# =====================================================================

@router.put(
    "/{id}/assign",
    response_model=FollowUpTaskResponse,
    status_code=status.HTTP_200_OK,
    summary="Assign a follow-up task",
    description=(
        "Assigns the task to an employee, or unassigns it with an explicit null. Appends a FOLLOW_UP "
        "entry to the lead's timeline recording the ownership change. Raises 404 for an unknown "
        "employee and 400 for an inactive one."
    ),
    dependencies=[Depends(RequirePermission("followups:update"))],
)
async def assign_followup(
    id: uuid.UUID,
    schema: FollowUpTaskAssign,
    db: AsyncSession = Depends(get_db),
    service: FollowUpTaskService = Depends(get_follow_up_task_service),
) -> FollowUpTaskResponse:
    """
    PUT /followups/{id}/assign Endpoint Flow:
    Validates the assignee -> Service (reassign + activity in one transaction) -> updated task.
    """
    return await service.assign_task(db=db, id=id, assigned_employee_id=schema.assigned_employee_id)


@router.put(
    "/{id}/complete",
    response_model=FollowUpTaskResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark a follow-up task complete",
    description=(
        "Marks the task COMPLETED, stamps completed_at, and appends the matching timeline entry — "
        "PHONE_CALL for a completed CALL task, TASK_COMPLETED otherwise. Raises 400 if the task is "
        "already completed or cancelled."
    ),
    dependencies=[Depends(RequirePermission("followups:update"))],
)
async def complete_followup(
    id: uuid.UUID,
    schema: FollowUpTaskComplete | None = None,
    db: AsyncSession = Depends(get_db),
    service: FollowUpTaskService = Depends(get_follow_up_task_service),
) -> FollowUpTaskResponse:
    """
    PUT /followups/{id}/complete Endpoint Flow:
    Validates the task is open -> Service (status + activity in one transaction) -> completed task.
    """
    return await service.complete_task(db=db, id=id, schema=schema)


@router.put(
    "/{id}/reschedule",
    response_model=FollowUpTaskResponse,
    status_code=status.HTTP_200_OK,
    summary="Reschedule a follow-up task",
    description=(
        "Moves the task to a new due time, returns an escalated task to PENDING, and appends a "
        "TASK_RESCHEDULED entry carrying both the old and new times. Raises 400 if the task is closed "
        "or if the new time equals the current one."
    ),
    dependencies=[Depends(RequirePermission("followups:update"))],
)
async def reschedule_followup(
    id: uuid.UUID,
    schema: FollowUpTaskReschedule,
    db: AsyncSession = Depends(get_db),
    service: FollowUpTaskService = Depends(get_follow_up_task_service),
) -> FollowUpTaskResponse:
    """
    PUT /followups/{id}/reschedule Endpoint Flow:
    Validates the task is open and actually moving -> Service -> rescheduled task.
    """
    return await service.reschedule_task(db=db, id=id, schema=schema)


@router.put(
    "/{id}/cancel",
    response_model=FollowUpTaskResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel a follow-up task",
    description=(
        "Marks the task CANCELLED and appends a TASK_CANCELLED entry to the lead's timeline. Use this "
        "rather than DELETE when the decision not to do the work is itself a fact about the lead."
    ),
    dependencies=[Depends(RequirePermission("followups:update"))],
)
async def cancel_followup(
    id: uuid.UUID,
    schema: FollowUpTaskCancel | None = None,
    db: AsyncSession = Depends(get_db),
    service: FollowUpTaskService = Depends(get_follow_up_task_service),
) -> FollowUpTaskResponse:
    """
    PUT /followups/{id}/cancel Endpoint Flow:
    Validates the task is open -> Service (status + activity in one transaction) -> cancelled task.
    """
    return await service.cancel_task(db=db, id=id, schema=schema)
