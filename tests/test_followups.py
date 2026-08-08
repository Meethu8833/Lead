"""
tests/test_followups.py

Integration test suite for the Follow-up & Task Management module.
Verifies:
1.  Task CRUD (create + validation, read, list/filter, update, soft delete).
2.  Assignment (assign, reassign, unassign, unknown/inactive employee rejection).
3.  Completion (status, completed_at, remarks, double-completion rejection).
4.  Rescheduling (new time, OVERDUE -> PENDING, no-op rejection, closed-task rejection).
5.  Cancellation, and how it differs from deletion.
6.  LeadActivity emission for every lifecycle event, with correct types and metadata.
7.  Today's tasks (window boundaries, exclusion of yesterday's and tomorrow's).
8.  Upcoming tasks (starts tomorrow, respects the `days` window, no overlap with today).
9.  Overdue tasks (derived rule: past-due PENDING counts without a sweeper).
10. Statistics (every counter, the breakdowns, and the completion-rate denominator).
11. Automatic task creation on a campaign reply ("interested" / "need_details" /
    "not_interested" / unclassified) and on a lead entering NEGOTIATION.
12. Automation de-duplication and the "never fail the triggering event" contract.
13. Soft-deleted leads never leak tasks into a worklist.
14. Optimistic locking (409 on a stale version).
15. RBAC (followups:view/create/update/delete enforced independently of leads:*).

This suite talks to the real configured database (see CLAUDE.md). Every row it creates is
explicitly hard-deleted in a `finally` block at the end, since the repository layer commits
each write immediately (a session-level rollback would not undo already-committed work).
Deleting the parent Lead rows cascades away their tasks and activities.
"""

import asyncio
import sys
import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, delete

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.core.context import audit_context
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
    ForbiddenException,
)
from app.models.lead import Lead, LeadStatus, LeadSource
from app.models.lead_activity import LeadActivity, ActivityType
from app.models.follow_up import (
    FollowUpTask,
    FollowUpType,
    FollowUpPriority,
    FollowUpStatus,
)
from app.models.employee import Employee
from app.models.role import Role
from app.schemas.lead import LeadCreate, LeadUpdate
from app.schemas.employee import EmployeeCreate
from app.schemas.follow_up import (
    FollowUpTaskCreate,
    FollowUpTaskUpdate,
    FollowUpTaskComplete,
    FollowUpTaskReschedule,
    FollowUpTaskCancel,
)
from app.services.lead import LeadService
from app.services.follow_up import (
    FollowUpTaskService,
    FollowUpAutomationService,
    day_bounds,
    is_task_overdue,
)
from app.services.employee import EmployeeService
from app.services.cache import permission_cache
from app.repositories.follow_up import FollowUpTaskRepository, AdminFollowUpTaskRepository
from app.api.deps import RequirePermission


def random_phone() -> str:
    return "".join(random.choices("0123456789", k=10))


async def activity_types_for(db, lead_id) -> list[ActivityType]:
    """
    Returns every activity type recorded against a lead, newest first.
    """
    rows = (await db.execute(
        select(LeadActivity)
        .where(LeadActivity.lead_id == lead_id)
        .order_by(LeadActivity.created_at.desc(), LeadActivity.id.desc())
    )).scalars().all()
    return [r.activity_type for r in rows]


async def latest_activity(db, lead_id, activity_type) -> LeadActivity | None:
    """
    Returns the most recent activity of a given type on a lead.
    """
    return (await db.execute(
        select(LeadActivity)
        .where(LeadActivity.lead_id == lead_id, LeadActivity.activity_type == activity_type)
        .order_by(LeadActivity.created_at.desc(), LeadActivity.id.desc())
        .limit(1)
    )).scalars().first()


async def test_followups_suite():
    print("=== STARTING FOLLOW-UP & TASK MANAGEMENT INTEGRATION TESTS ===")

    lead_service = LeadService()
    task_service = FollowUpTaskService()
    automation = FollowUpAutomationService()
    employee_service = EmployeeService()
    repository = FollowUpTaskRepository()
    unique_suffix = str(uuid.uuid4())[:8]

    created_lead_ids: list[uuid.UUID] = []
    created_employee_ids: list[uuid.UUID] = []

    async with AsyncSessionLocal() as db:
        try:
            # ==========================================================
            # [0] SETUP: roles, employees, acting-user context
            # ==========================================================
            print("\n--- [0] SETUP: ROLES, EMPLOYEES & AUDIT CONTEXT ---")
            admin_role = (await db.execute(select(Role).where(Role.name == "Administrator"))).scalars().first()
            viewer_role = (await db.execute(select(Role).where(Role.name == "Viewer"))).scalars().first()
            designer_role = (await db.execute(select(Role).where(Role.name == "Designer"))).scalars().first()
            reception_role = (await db.execute(select(Role).where(Role.name == "Reception"))).scalars().first()
            assert admin_role and viewer_role and designer_role and reception_role, \
                "Seed roles missing — run `python scripts/seed_roles.py` first."

            actor = await employee_service.create_employee(db, EmployeeCreate(
                first_name="FollowUpActor", last_name="Test",
                email=f"fu_actor_{unique_suffix}@colourlabs.com",
                phone=random_phone(), password="SecurePassword123!", role_id=admin_role.id,
            ))
            created_employee_ids.append(actor.id)

            owner = await employee_service.create_employee(db, EmployeeCreate(
                first_name="FollowUpOwner", last_name="Test",
                email=f"fu_owner_{unique_suffix}@colourlabs.com",
                phone=random_phone(), password="SecurePassword123!", role_id=reception_role.id,
            ))
            created_employee_ids.append(owner.id)

            other_owner = await employee_service.create_employee(db, EmployeeCreate(
                first_name="FollowUpOther", last_name="Test",
                email=f"fu_other_{unique_suffix}@colourlabs.com",
                phone=random_phone(), password="SecurePassword123!", role_id=reception_role.id,
            ))
            created_employee_ids.append(other_owner.id)

            viewer_employee = await employee_service.create_employee(db, EmployeeCreate(
                first_name="FollowUpViewer", last_name="Test",
                email=f"fu_viewer_{unique_suffix}@colourlabs.com",
                phone=random_phone(), password="SecurePassword123!", role_id=viewer_role.id,
            ))
            created_employee_ids.append(viewer_employee.id)

            designer_employee = await employee_service.create_employee(db, EmployeeCreate(
                first_name="FollowUpDesigner", last_name="Test",
                email=f"fu_designer_{unique_suffix}@colourlabs.com",
                phone=random_phone(), password="SecurePassword123!", role_id=designer_role.id,
            ))
            created_employee_ids.append(designer_employee.id)

            audit_context.set({
                "user_id": str(actor.id),
                "ip_address": "192.168.1.88",
                "user_agent": "Mozilla/5.0 (Follow-Up Test Agent)",
            })

            marker = f"FollowUpMarker{unique_suffix}"
            print(f"Created 5 test employees; acting employee = {actor.id}")

            async def make_lead(name: str, **kwargs) -> Lead:
                lead = await lead_service.create_lead(db, LeadCreate(
                    business_name=f"{marker} {name}",
                    phone=random_phone(),
                    source=LeadSource.MANUAL,
                    **kwargs,
                ))
                created_lead_ids.append(lead.id)
                return lead

            now = datetime.now(timezone.utc)
            start_today, tomorrow = day_bounds(now)

            # ==========================================================
            # [1] TASK CREATION + VALIDATION
            # ==========================================================
            print("\n--- [1] TASK CREATION & VALIDATION ---")
            lead_a = await make_lead("Alpha", assigned_employee_id=owner.id)

            task = await task_service.create_task(db, FollowUpTaskCreate(
                lead_id=lead_a.id,
                title="Call Alpha Studio about the wedding package",
                description="Discuss the premium album tier.",
                follow_up_type=FollowUpType.CALL,
                priority=FollowUpPriority.HIGH,
                scheduled_at=now + timedelta(hours=3),
                assigned_employee_id=owner.id,
            ))
            assert task.id is not None
            assert task.status == FollowUpStatus.PENDING
            assert task.priority == FollowUpPriority.HIGH
            assert task.follow_up_type == FollowUpType.CALL
            assert task.assigned_employee_id == owner.id
            assert task.completed_at is None
            assert task.version == 1
            assert task.is_overdue is False
            print(f"Created task {task.id} (PENDING, HIGH, CALL).")

            # An unknown lead is rejected.
            try:
                await task_service.create_task(db, FollowUpTaskCreate(
                    lead_id=uuid.uuid4(), title="Ghost task",
                    scheduled_at=now + timedelta(hours=1),
                ))
                assert False, "Task creation against an unknown lead did not raise"
            except NotFoundException:
                print("Unknown lead rejected on create.")

            # An unknown assignee is rejected.
            try:
                await task_service.create_task(db, FollowUpTaskCreate(
                    lead_id=lead_a.id, title="Bad assignee",
                    scheduled_at=now + timedelta(hours=1),
                    assigned_employee_id=uuid.uuid4(),
                ))
                assert False, "Task creation with an unknown assignee did not raise"
            except NotFoundException:
                print("Unknown assignee rejected on create.")

            # A blank title is rejected at the schema layer.
            try:
                FollowUpTaskCreate(
                    lead_id=lead_a.id, title="   ",
                    scheduled_at=now + timedelta(hours=1),
                )
                assert False, "Blank title was accepted"
            except Exception:
                print("Blank title rejected by the schema.")

            # A naive datetime is normalized to UTC rather than exploding downstream.
            naive_schema = FollowUpTaskCreate(
                lead_id=lead_a.id, title="Naive datetime task",
                scheduled_at=datetime(2030, 1, 1, 12, 0, 0),
            )
            assert naive_schema.scheduled_at.tzinfo is not None, "Naive datetime was not normalized"
            print("Naive scheduled_at normalized to timezone-aware UTC.")

            # A back-dated task is allowed and lands as overdue.
            backdated = await task_service.create_task(db, FollowUpTaskCreate(
                lead_id=lead_a.id, title="Back-filled call that should have happened",
                follow_up_type=FollowUpType.CALL,
                scheduled_at=now - timedelta(days=2),
                assigned_employee_id=owner.id,
            ))
            assert backdated.is_overdue is True, "A past-due PENDING task must read as overdue"
            print("Back-dated task accepted and flagged overdue.")

            # ==========================================================
            # [2] ACTIVITY EMISSION ON CREATE
            # ==========================================================
            print("\n--- [2] LEADACTIVITY ON TASK CREATION ---")
            types_a = await activity_types_for(db, lead_a.id)
            assert ActivityType.TASK_CREATED in types_a, "TASK_CREATED was not emitted"
            created_activity = await latest_activity(db, lead_a.id, ActivityType.TASK_CREATED)
            assert created_activity.activity_metadata["task_id"] == str(backdated.id)
            assert created_activity.activity_metadata["follow_up_type"] == "CALL"
            assert created_activity.created_by_employee_id == actor.id, \
                "Activity was not attributed to the acting employee"
            print("TASK_CREATED emitted with correct metadata and attribution.")

            # A MEETING task additionally emits MEETING_SCHEDULED.
            lead_meeting = await make_lead("MeetingCo", assigned_employee_id=owner.id)
            meeting_task = await task_service.create_task(db, FollowUpTaskCreate(
                lead_id=lead_meeting.id, title="Site visit and pricing discussion",
                follow_up_type=FollowUpType.MEETING,
                priority=FollowUpPriority.URGENT,
                scheduled_at=now + timedelta(days=1, hours=2),
                assigned_employee_id=owner.id,
            ))
            meeting_types = await activity_types_for(db, lead_meeting.id)
            assert ActivityType.TASK_CREATED in meeting_types
            assert ActivityType.MEETING_SCHEDULED in meeting_types, \
                "A MEETING task must also emit MEETING_SCHEDULED"
            print("MEETING task emitted both TASK_CREATED and MEETING_SCHEDULED.")

            # ==========================================================
            # [3] READ / LIST / FILTER
            # ==========================================================
            print("\n--- [3] READ, LIST & FILTER ---")
            fetched = await task_service.get_task_by_id(db, task.id)
            assert fetched.id == task.id

            try:
                await task_service.get_task_by_id(db, uuid.uuid4())
                assert False, "Unknown task ID did not raise"
            except NotFoundException:
                print("Unknown task ID raises NotFoundException.")

            by_lead, by_lead_total = await task_service.get_all_tasks(db, lead_id=lead_a.id)
            assert by_lead_total == 2, f"Expected 2 tasks on lead A, got {by_lead_total}"
            # Ordering is soonest-due first, so the back-dated task comes first.
            assert by_lead[0].id == backdated.id, "Worklist ordering is not soonest-due-first"
            print(f"Lead-scoped list returned {by_lead_total} tasks in soonest-due order.")

            by_type, by_type_total = await task_service.get_all_tasks(
                db, lead_id=lead_a.id, follow_up_type=FollowUpType.CALL
            )
            assert by_type_total == 2
            by_prio, by_prio_total = await task_service.get_all_tasks(
                db, lead_id=lead_a.id, priority=FollowUpPriority.HIGH
            )
            assert by_prio_total == 1 and by_prio[0].id == task.id
            by_status, by_status_total = await task_service.get_all_tasks(
                db, lead_id=lead_a.id, status=FollowUpStatus.PENDING
            )
            assert by_status_total == 2
            searched, searched_total = await task_service.get_all_tasks(
                db, lead_id=lead_a.id, search="wedding package"
            )
            assert searched_total == 1 and searched[0].id == task.id
            print("Filters by type, priority, status and search all correct.")

            # Pagination: no overlap, no gaps.
            page1, total1 = await task_service.get_all_tasks(db, lead_id=lead_a.id, skip=0, limit=1)
            page2, total2 = await task_service.get_all_tasks(db, lead_id=lead_a.id, skip=1, limit=1)
            assert total1 == total2 == 2
            assert len(page1) == len(page2) == 1
            assert page1[0].id != page2[0].id, "Pagination returned an overlapping row"
            print("Pagination is stable across pages.")

            # ==========================================================
            # [4] UPDATE + OPTIMISTIC LOCKING
            # ==========================================================
            print("\n--- [4] UPDATE & OPTIMISTIC LOCKING ---")
            updated = await task_service.update_task(db, task.id, FollowUpTaskUpdate(
                title="Call Alpha Studio — premium tier",
                priority=FollowUpPriority.URGENT,
                version=task.version,
            ))
            assert updated.title == "Call Alpha Studio — premium tier"
            assert updated.priority == FollowUpPriority.URGENT
            assert updated.version == 2, f"Version did not bump, got {updated.version}"
            print(f"Task updated; version bumped to {updated.version}.")

            try:
                await task_service.update_task(db, task.id, FollowUpTaskUpdate(
                    title="Stale write", version=1,
                ))
                assert False, "Stale version did not raise ConflictException"
            except ConflictException:
                print("Optimistic locking rejects a stale version.")

            # ==========================================================
            # [5] ASSIGNMENT
            # ==========================================================
            print("\n--- [5] ASSIGNMENT ---")
            reassigned = await task_service.assign_task(db, task.id, other_owner.id)
            assert reassigned.assigned_employee_id == other_owner.id
            assign_activity = await latest_activity(db, lead_a.id, ActivityType.FOLLOW_UP)
            assert assign_activity is not None, "Reassignment emitted no activity"
            assert assign_activity.activity_metadata["previous_employee_id"] == str(owner.id)
            assert assign_activity.activity_metadata["new_employee_id"] == str(other_owner.id)
            print("Reassignment recorded on the timeline with old and new owner.")

            # A no-op assignment writes nothing.
            activity_count_before = len(await activity_types_for(db, lead_a.id))
            await task_service.assign_task(db, task.id, other_owner.id)
            activity_count_after = len(await activity_types_for(db, lead_a.id))
            assert activity_count_after == activity_count_before, \
                "A no-op reassignment wrote a spurious activity"
            print("No-op reassignment writes no activity.")

            # Unassignment is a real operation.
            unassigned = await task_service.assign_task(db, task.id, None)
            assert unassigned.assigned_employee_id is None
            print("Unassignment supported.")
            await task_service.assign_task(db, task.id, owner.id)

            # An inactive employee cannot be assigned work.
            inactive = await employee_service.create_employee(db, EmployeeCreate(
                first_name="FollowUpInactive", last_name="Test",
                email=f"fu_inactive_{unique_suffix}@colourlabs.com",
                phone=random_phone(), password="SecurePassword123!", role_id=reception_role.id,
            ))
            created_employee_ids.append(inactive.id)
            inactive_row = await db.get(Employee, inactive.id)
            inactive_row.is_active = False
            db.add(inactive_row)
            await db.commit()
            try:
                await task_service.assign_task(db, task.id, inactive.id)
                assert False, "An inactive employee was accepted as an assignee"
            except BadRequestException:
                print("Inactive employee rejected as an assignee.")

            # ==========================================================
            # [6] RESCHEDULING
            # ==========================================================
            print("\n--- [6] RESCHEDULING ---")
            new_time = now + timedelta(days=3, hours=1)
            rescheduled = await task_service.reschedule_task(db, backdated.id, FollowUpTaskReschedule(
                scheduled_at=new_time,
                remarks="Lead asked us to call back next week.",
            ))
            assert rescheduled.scheduled_at.replace(microsecond=0) == new_time.replace(microsecond=0)
            assert rescheduled.status == FollowUpStatus.PENDING
            assert rescheduled.is_overdue is False, "A rescheduled future task must not read overdue"
            resched_activity = await latest_activity(db, lead_a.id, ActivityType.TASK_RESCHEDULED)
            assert resched_activity is not None, "TASK_RESCHEDULED was not emitted"
            assert resched_activity.activity_metadata["new_scheduled_at"] is not None
            assert resched_activity.activity_metadata["old_scheduled_at"] is not None
            print("Rescheduling moved the task, cleared overdue, and recorded both times.")

            # Rescheduling to the same instant is a no-op decision and is rejected.
            try:
                await task_service.reschedule_task(db, backdated.id, FollowUpTaskReschedule(
                    scheduled_at=rescheduled.scheduled_at,
                ))
                assert False, "Rescheduling to the same time did not raise"
            except BadRequestException:
                print("Rescheduling to an identical time rejected.")

            # ==========================================================
            # [7] COMPLETION
            # ==========================================================
            print("\n--- [7] COMPLETION ---")
            completed = await task_service.complete_task(db, task.id, FollowUpTaskComplete(
                remarks="Spoke to the owner; sending a quote for the premium tier.",
            ))
            assert completed.status == FollowUpStatus.COMPLETED
            assert completed.completed_at is not None
            assert completed.remarks.startswith("Spoke to the owner")
            assert completed.is_overdue is False, "A completed task must never read as overdue"
            # A completed CALL records a PHONE_CALL, not a generic TASK_COMPLETED.
            call_activity = await latest_activity(db, lead_a.id, ActivityType.PHONE_CALL)
            assert call_activity is not None, "A completed CALL task did not emit PHONE_CALL"
            assert call_activity.activity_metadata["task_id"] == str(task.id)
            print("CALL completion recorded as PHONE_CALL with outcome remarks.")

            # A non-CALL completion records TASK_COMPLETED.
            completed_meeting = await task_service.complete_task(db, meeting_task.id, FollowUpTaskComplete(
                remarks="Met at the studio; agreed on the album spec.",
            ))
            assert completed_meeting.status == FollowUpStatus.COMPLETED
            meeting_done = await latest_activity(db, lead_meeting.id, ActivityType.TASK_COMPLETED)
            assert meeting_done is not None, "A completed MEETING task did not emit TASK_COMPLETED"
            print("MEETING completion recorded as TASK_COMPLETED.")

            # A completed task cannot be completed, rescheduled or reassigned again.
            for op_name, coro in (
                ("complete", task_service.complete_task(db, task.id, None)),
                ("reschedule", task_service.reschedule_task(
                    db, task.id, FollowUpTaskReschedule(scheduled_at=now + timedelta(days=9)))),
                ("assign", task_service.assign_task(db, task.id, other_owner.id)),
                ("update", task_service.update_task(db, task.id, FollowUpTaskUpdate(title="Nope"))),
            ):
                try:
                    await coro
                    assert False, f"A closed task accepted a {op_name} operation"
                except BadRequestException:
                    pass
            print("A completed task rejects complete/reschedule/assign/update.")

            # ==========================================================
            # [8] CANCELLATION & DELETION
            # ==========================================================
            print("\n--- [8] CANCELLATION & DELETION ---")
            lead_cancel = await make_lead("CancelCo", assigned_employee_id=owner.id)
            to_cancel = await task_service.create_task(db, FollowUpTaskCreate(
                lead_id=lead_cancel.id, title="Send follow-up brochure",
                follow_up_type=FollowUpType.EMAIL,
                scheduled_at=now + timedelta(days=2),
                assigned_employee_id=owner.id,
            ))
            cancelled = await task_service.cancel_task(db, to_cancel.id, FollowUpTaskCancel(
                remarks="Lead signed with a competitor.",
            ))
            assert cancelled.status == FollowUpStatus.CANCELLED
            assert cancelled.is_overdue is False
            cancel_activity = await latest_activity(db, lead_cancel.id, ActivityType.TASK_CANCELLED)
            assert cancel_activity is not None, "TASK_CANCELLED was not emitted"
            print("Cancellation recorded on the timeline.")

            # Deleting is a soft delete, writes no activity, and hides the task from reads.
            to_delete = await task_service.create_task(db, FollowUpTaskCreate(
                lead_id=lead_cancel.id, title="Duplicate task created by mistake",
                scheduled_at=now + timedelta(days=2),
            ))
            before_delete = len(await activity_types_for(db, lead_cancel.id))
            await task_service.delete_task(db, to_delete.id)
            after_delete = len(await activity_types_for(db, lead_cancel.id))
            assert after_delete == before_delete, "Deletion wrote a timeline entry; it should not"
            try:
                await task_service.get_task_by_id(db, to_delete.id)
                assert False, "A soft-deleted task was still readable"
            except NotFoundException:
                pass
            admin_repo = AdminFollowUpTaskRepository()
            still_there = await admin_repo.get_by_id(db, to_delete.id)
            assert still_there is not None and still_there.is_deleted is True
            print("Deletion soft-deletes, writes no activity, and stays visible to the admin repo.")

            # ==========================================================
            # [9] TODAY / UPCOMING / OVERDUE WORKLISTS
            # ==========================================================
            print("\n--- [9] WORKLISTS: TODAY, UPCOMING, OVERDUE ---")
            lead_w = await make_lead("WorklistCo", assigned_employee_id=other_owner.id)

            # Place one task in each window, all owned by `other_owner` so the worklists can
            # be scoped to that employee and remain unaffected by other suites' data.
            due_today = await task_service.create_task(db, FollowUpTaskCreate(
                lead_id=lead_w.id, title="Due later today",
                scheduled_at=start_today + timedelta(hours=23, minutes=30),
                assigned_employee_id=other_owner.id,
            ))
            due_tomorrow = await task_service.create_task(db, FollowUpTaskCreate(
                lead_id=lead_w.id, title="Due tomorrow",
                scheduled_at=tomorrow + timedelta(hours=10),
                assigned_employee_id=other_owner.id,
            ))
            due_next_month = await task_service.create_task(db, FollowUpTaskCreate(
                lead_id=lead_w.id, title="Due in 30 days",
                scheduled_at=tomorrow + timedelta(days=30),
                assigned_employee_id=other_owner.id,
            ))
            was_due_yesterday = await task_service.create_task(db, FollowUpTaskCreate(
                lead_id=lead_w.id, title="Was due yesterday",
                follow_up_type=FollowUpType.WHATSAPP,
                scheduled_at=start_today - timedelta(hours=5),
                assigned_employee_id=other_owner.id,
            ))

            today_items, today_total = await task_service.get_todays_tasks(
                db, assigned_employee_id=other_owner.id
            )
            today_ids = {t.id for t in today_items}
            assert due_today.id in today_ids, "A task due today is missing from today's list"
            assert due_tomorrow.id not in today_ids, "Tomorrow's task leaked into today's list"
            assert was_due_yesterday.id not in today_ids, "An overdue task leaked into today's list"
            print(f"Today's list: {today_total} task(s), correctly windowed.")

            upcoming_items, upcoming_total = await task_service.get_upcoming_tasks(
                db, assigned_employee_id=other_owner.id, days=7
            )
            upcoming_ids = {t.id for t in upcoming_items}
            assert due_tomorrow.id in upcoming_ids, "Tomorrow's task is missing from upcoming"
            assert due_today.id not in upcoming_ids, "Today's task leaked into upcoming (overlap)"
            assert due_next_month.id not in upcoming_ids, "A task beyond the window leaked into upcoming"
            print(f"Upcoming (7d): {upcoming_total} task(s); no overlap with today.")

            wide_items, _ = await task_service.get_upcoming_tasks(
                db, assigned_employee_id=other_owner.id, days=60
            )
            assert due_next_month.id in {t.id for t in wide_items}, \
                "Widening the window did not pick up the distant task"
            print("Widening the `days` window picks up more distant tasks.")

            overdue_items, overdue_total = await task_service.get_overdue_tasks(
                db, assigned_employee_id=other_owner.id
            )
            overdue_ids = {t.id for t in overdue_items}
            assert was_due_yesterday.id in overdue_ids, \
                "A past-due PENDING task is missing from overdue (the derived rule failed)"
            assert due_today.id not in overdue_ids
            assert all(t.is_overdue for t in overdue_items), \
                "The overdue list returned a task whose is_overdue flag disagrees"
            print(f"Overdue: {overdue_total} task(s); derived rule works with no sweeper.")

            # The stored-OVERDUE half of the rule also works.
            stored_overdue_row = await db.get(FollowUpTask, was_due_yesterday.id)
            stored_overdue_row.status = FollowUpStatus.OVERDUE
            db.add(stored_overdue_row)
            await db.commit()
            overdue_items2, _ = await task_service.get_overdue_tasks(
                db, assigned_employee_id=other_owner.id
            )
            assert was_due_yesterday.id in {t.id for t in overdue_items2}, \
                "A stored-OVERDUE task fell out of the overdue list"
            print("A stored OVERDUE status is also honoured by the overdue list.")

            # A rescheduled overdue task returns to PENDING.
            back_to_pending = await task_service.reschedule_task(
                db, was_due_yesterday.id,
                FollowUpTaskReschedule(scheduled_at=tomorrow + timedelta(hours=9)),
            )
            assert back_to_pending.status == FollowUpStatus.PENDING, \
                "Rescheduling an OVERDUE task did not return it to PENDING"
            print("Rescheduling an OVERDUE task returns it to PENDING.")

            # ==========================================================
            # [10] SOFT-DELETED LEADS DO NOT LEAK TASKS
            # ==========================================================
            print("\n--- [10] SOFT-DELETED LEAD ISOLATION ---")
            lead_gone = await make_lead("SoonDeleted", assigned_employee_id=other_owner.id)
            orphan = await task_service.create_task(db, FollowUpTaskCreate(
                lead_id=lead_gone.id, title="Task on a lead about to be deleted",
                scheduled_at=start_today + timedelta(hours=20),
                assigned_employee_id=other_owner.id,
            ))
            today_before, _ = await task_service.get_todays_tasks(db, assigned_employee_id=other_owner.id)
            assert orphan.id in {t.id for t in today_before}

            await lead_service.delete_lead(db, lead_gone.id)

            today_after, _ = await task_service.get_todays_tasks(db, assigned_employee_id=other_owner.id)
            assert orphan.id not in {t.id for t in today_after}, \
                "A task belonging to a soft-deleted lead is still on the worklist"
            listed, _ = await task_service.get_all_tasks(db, assigned_employee_id=other_owner.id)
            assert orphan.id not in {t.id for t in listed}, \
                "A task belonging to a soft-deleted lead is still in the task list"
            print("Tasks of a soft-deleted lead vanish from every worklist.")

            # ==========================================================
            # [11] AUTOMATIC TASK CREATION
            # ==========================================================
            print("\n--- [11] AUTOMATION: CAMPAIGN REPLIES ---")

            # "interested" -> a HIGH priority CALL.
            lead_int = await make_lead("InterestedCo", assigned_employee_id=owner.id)
            auto_call = await automation.on_campaign_reply(
                db, lead=lead_int, reply_type="interested", commit=True
            )
            assert auto_call is not None, "An 'interested' reply created no follow-up task"
            assert auto_call.follow_up_type == FollowUpType.CALL
            assert auto_call.priority == FollowUpPriority.HIGH
            assert auto_call.status == FollowUpStatus.PENDING
            assert auto_call.assigned_employee_id == owner.id, \
                "The automated task did not inherit the lead's owner"
            auto_activity = await latest_activity(db, lead_int.id, ActivityType.TASK_CREATED)
            assert auto_activity.activity_metadata["automated"] is True
            assert auto_activity.activity_metadata["trigger"] == "reply_interested"
            print("'interested' -> HIGH CALL task, owner inherited, activity flagged automated.")

            # De-duplication: a second identical reply does not stack a second task.
            duplicate = await automation.on_campaign_reply(
                db, lead=lead_int, reply_type="interested", commit=True
            )
            assert duplicate is None, "A repeated reply created a duplicate open task"
            _, int_total = await task_service.get_all_tasks(db, lead_id=lead_int.id)
            assert int_total == 1, f"Expected 1 task after a repeat reply, got {int_total}"
            print("A repeated reply is de-duplicated to a single open task.")

            # ...but after the first is completed, a genuine new follow-up is created.
            await task_service.complete_task(db, auto_call.id, None)
            after_completion = await automation.on_campaign_reply(
                db, lead=lead_int, reply_type="interested", commit=True
            )
            assert after_completion is not None, \
                "No new task was created after the previous one was completed"
            print("A new reply after completion does create a fresh task.")

            # "need_details" -> a MEDIUM priority WHATSAPP task.
            lead_det = await make_lead("NeedDetailsCo", assigned_employee_id=owner.id)
            auto_wa = await automation.on_campaign_reply(
                db, lead=lead_det, reply_type="need_details", commit=True
            )
            assert auto_wa is not None
            assert auto_wa.follow_up_type == FollowUpType.WHATSAPP
            assert auto_wa.priority == FollowUpPriority.MEDIUM
            print("'need_details' -> MEDIUM WHATSAPP task.")

            # "not_interested" -> no task at all.
            lead_no = await make_lead("NotInterestedCo", assigned_employee_id=owner.id)
            auto_none = await automation.on_campaign_reply(
                db, lead=lead_no, reply_type="not_interested", commit=True
            )
            assert auto_none is None, "'not_interested' should create no task"
            _, no_total = await task_service.get_all_tasks(db, lead_id=lead_no.id)
            assert no_total == 0
            print("'not_interested' -> no task, as intended.")

            # An unclassified reply routes to manual review rather than falling on the floor.
            lead_unknown = await make_lead("UnclassifiedCo", assigned_employee_id=owner.id)
            auto_manual = await automation.on_campaign_reply(
                db, lead=lead_unknown, reply_type=None, commit=True
            )
            assert auto_manual is not None, "An unclassified reply created no task"
            assert auto_manual.title == "Review campaign reply"
            manual_activity = await latest_activity(db, lead_unknown.id, ActivityType.TASK_CREATED)
            assert manual_activity.activity_metadata["trigger"] == "manual_contact_required"
            print("An unclassified reply routes to manual_contact_required.")

            print("\n--- [12] AUTOMATION: NEGOTIATION STATUS ---")
            lead_neg = await make_lead("NegotiationCo", assigned_employee_id=owner.id)
            negotiated = await lead_service.update_lead(db, lead_neg.id, LeadUpdate(
                status=LeadStatus.NEGOTIATION, version=lead_neg.version,
            ))
            assert negotiated.status == LeadStatus.NEGOTIATION
            neg_tasks, neg_total = await task_service.get_all_tasks(db, lead_id=lead_neg.id)
            assert neg_total == 1, f"Entering NEGOTIATION created {neg_total} tasks, expected 1"
            neg_task = neg_tasks[0]
            assert neg_task.follow_up_type == FollowUpType.MEETING
            assert neg_task.priority == FollowUpPriority.URGENT
            neg_types = await activity_types_for(db, lead_neg.id)
            assert ActivityType.MEETING_SCHEDULED in neg_types
            assert ActivityType.STATUS_CHANGED in neg_types
            print("NEGOTIATION -> URGENT MEETING task + MEETING_SCHEDULED activity.")

            # Re-saving a lead already in negotiation must not stack another meeting.
            await lead_service.update_lead(db, lead_neg.id, LeadUpdate(
                remarks="Quoted 85k for the full package.", version=negotiated.version,
            ))
            _, neg_total2 = await task_service.get_all_tasks(db, lead_id=lead_neg.id)
            assert neg_total2 == 1, "A second update stacked a duplicate negotiation task"
            print("Re-saving a negotiating lead does not stack duplicate meetings.")

            # A different status transition raises nothing.
            lead_contacted = await make_lead("ContactedCo", assigned_employee_id=owner.id)
            await lead_service.update_lead(db, lead_contacted.id, LeadUpdate(
                status=LeadStatus.CONTACTED, version=lead_contacted.version,
            ))
            _, contacted_total = await task_service.get_all_tasks(db, lead_id=lead_contacted.id)
            assert contacted_total == 0, "A non-NEGOTIATION status change created a task"
            print("Other status transitions create no task.")

            # The automation must never cost its caller the triggering domain event. A lead
            # whose row does not exist drives the insert into an FK violation, which is the
            # hard case: swallowing the exception alone is NOT enough, because a DB-level
            # error poisons the session and the caller's own commit would then fail with
            # PendingRollbackError. The savepoint in _safe_create is what makes the caller's
            # transaction survive, so this asserts both halves.
            lead_survivor = await make_lead("SurvivorCo", assigned_employee_id=owner.id)
            survivor_task = await task_service.create_task(db, FollowUpTaskCreate(
                lead_id=lead_survivor.id, title="Primary work that must not be lost",
                scheduled_at=now + timedelta(days=1),
            ))

            phantom = Lead(
                id=uuid.uuid4(), business_name="Phantom", phone=random_phone(),
                status=LeadStatus.NEW, source=LeadSource.MANUAL,
            )
            survived = await automation.on_campaign_reply(
                db, lead=phantom, reply_type="interested", commit=False
            )
            assert survived is None, "A failing automation should return None, not raise"

            # The session must still be usable — this is the part a bare try/except misses.
            pending_work = await task_service.update_task(
                db, survivor_task.id,
                FollowUpTaskUpdate(remarks="Committed after a failed automation."),
            )
            assert pending_work.remarks == "Committed after a failed automation.", \
                "The caller's transaction did not survive a failed automation"
            print("A failing automation is swallowed AND leaves the caller's session usable.")

            # ==========================================================
            # [13] STATISTICS
            # ==========================================================
            print("\n--- [13] STATISTICS ---")
            stats = await task_service.get_statistics(db, assigned_employee_id=other_owner.id)
            assert stats["assigned_employee_id"] == other_owner.id
            assert stats["total"] >= 3
            assert isinstance(stats["by_status"], dict) and stats["by_status"]
            assert isinstance(stats["by_type"], dict) and stats["by_type"]
            assert isinstance(stats["by_priority"], dict) and stats["by_priority"]
            assert 0.0 <= stats["completion_rate"] <= 100.0
            # The counters must partition: pending (open, not late) + overdue + completed
            # + cancelled can never exceed the total.
            assert stats["pending"] + stats["overdue"] + stats["completed"] + stats["cancelled"] <= stats["total"], \
                "Statistics counters overlap; they must partition the task set"
            print(
                f"Stats(other_owner): total={stats['total']} pending={stats['pending']} "
                f"overdue={stats['overdue']} completed={stats['completed']} "
                f"cancelled={stats['cancelled']} due_today={stats['due_today']} "
                f"rate={stats['completion_rate']}%"
            )

            # The completion rate is over resolved work, not over everything.
            lead_rate = await make_lead("RateCo", assigned_employee_id=inactive.id)
            rate_tasks = []
            for i in range(4):
                t = await task_service.create_task(db, FollowUpTaskCreate(
                    lead_id=lead_rate.id, title=f"Rate task {i}",
                    scheduled_at=now + timedelta(days=1, hours=i),
                ))
                # Assign directly (the employee is inactive, so the service would reject it)
                # to build a clean, isolated statistics scope.
                row = await db.get(FollowUpTask, t.id)
                row.assigned_employee_id = inactive.id
                db.add(row)
                await db.commit()
                rate_tasks.append(t)

            await task_service.complete_task(db, rate_tasks[0].id, None)
            await task_service.complete_task(db, rate_tasks[1].id, None)
            await task_service.complete_task(db, rate_tasks[2].id, None)
            await task_service.cancel_task(db, rate_tasks[3].id, None)

            rate_stats = await task_service.get_statistics(db, assigned_employee_id=inactive.id)
            assert rate_stats["total"] == 4
            assert rate_stats["completed"] == 3
            assert rate_stats["cancelled"] == 1
            assert rate_stats["completion_rate"] == 75.0, \
                f"Completion rate should be 75.0 (3 of 4 resolved), got {rate_stats['completion_rate']}"
            assert rate_stats["by_status"].get("COMPLETED") == 3
            print("Completion rate is computed over resolved tasks (3/4 = 75.0%).")

            # ==========================================================
            # [14] RBAC
            # ==========================================================
            print("\n--- [14] RBAC ---")
            await permission_cache.invalidate_employee(viewer_employee.id)
            await permission_cache.invalidate_employee(designer_employee.id)
            await permission_cache.invalidate_employee(owner.id)

            # Viewer holds *:view — followups:view passes, followups:create must not.
            view_dep = RequirePermission("followups:view")
            create_dep = RequirePermission("followups:create")
            update_dep = RequirePermission("followups:update")
            delete_dep = RequirePermission("followups:delete")

            await view_dep(db=db, current_employee=viewer_employee, employee_service=employee_service)
            print("Viewer can read follow-ups (via *:view).")

            for dep, label in ((create_dep, "create"), (update_dep, "update"), (delete_dep, "delete")):
                try:
                    await dep(db=db, current_employee=viewer_employee, employee_service=employee_service)
                    assert False, f"Viewer was allowed followups:{label}"
                except ForbiddenException:
                    pass
            print("Viewer denied create/update/delete.")

            # Designer holds no followups permission at all.
            try:
                await view_dep(db=db, current_employee=designer_employee, employee_service=employee_service)
                assert False, "Designer was allowed followups:view"
            except ForbiddenException:
                print("Designer denied followups:view entirely.")

            # Reception works the queue but cannot delete.
            await view_dep(db=db, current_employee=owner, employee_service=employee_service)
            await create_dep(db=db, current_employee=owner, employee_service=employee_service)
            await update_dep(db=db, current_employee=owner, employee_service=employee_service)
            try:
                await delete_dep(db=db, current_employee=owner, employee_service=employee_service)
                assert False, "Reception was allowed followups:delete"
            except ForbiddenException:
                print("Reception can view/create/update but not delete.")

            # ==========================================================
            # [15] REGRESSION: EXISTING LEAD BEHAVIOUR UNCHANGED
            # ==========================================================
            print("\n--- [15] REGRESSION CHECKS ---")
            reg_lead = await make_lead("RegressionCo")
            assert reg_lead.status == LeadStatus.NEW
            reg_types = await activity_types_for(db, reg_lead.id)
            assert ActivityType.CREATED in reg_types, "Lead creation stopped emitting CREATED"

            reg_updated = await lead_service.update_lead(db, reg_lead.id, LeadUpdate(
                remarks="Still working normally.", version=reg_lead.version,
            ))
            assert reg_updated.version == 2
            reg_types2 = await activity_types_for(db, reg_lead.id)
            assert ActivityType.UPDATED in reg_types2, "Lead update stopped emitting UPDATED"

            found, found_total = await lead_service.get_all_leads(db, search=marker)
            assert found_total >= 5
            print(f"Lead CRUD, timeline and search all unaffected ({found_total} leads matched).")

            print("\n=== ALL FOLLOW-UP & TASK MANAGEMENT INTEGRATION TESTS COMPLETED SUCCESSFULLY ===")

        except Exception as e:
            print(f"\nTEST SUITE FAILED WITH ERROR: {e}")
            import traceback
            traceback.print_exc()
            raise e
        finally:
            # Repository writes commit immediately, so we explicitly hard-delete everything
            # this suite created. Deleting a Lead cascades its follow-up tasks and activities
            # away (FK ON DELETE CASCADE), so those need no separate cleanup.
            print("\nCleaning up test data...")
            await db.rollback()
            for lead_id in created_lead_ids:
                row = await db.get(Lead, lead_id)
                if row:
                    await db.delete(row)
            await db.commit()
            for employee_id in created_employee_ids:
                row = await db.get(Employee, employee_id)
                if row:
                    await db.delete(row)
            await db.commit()
            print("Cleanup complete.")


if __name__ == "__main__":
    asyncio.run(test_followups_suite())
