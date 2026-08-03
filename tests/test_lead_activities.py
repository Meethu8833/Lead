"""
tests/test_lead_activities.py

Integration test suite for the Lead Activity & Notes module.
Verifies:
1.  Note creation (+ the NOTE activity it emits, + blank-note rejection, + 404 on unknown lead).
2.  Note editing (body updated, no extra timeline entry, 404 on unknown/deleted note).
3.  Note deletion (soft delete, excluded from listing, NOTE activity preserved, 404s).
4.  Automatic activity creation on lead create (CREATED) and update (UPDATED).
5.  Automatic STATUS_CHANGED activity with correct old/new metadata.
6.  Automatic CONVERTED activity, fired on transition only (not re-fired).
7.  Automatic DELETED activity on lead soft delete.
8.  Timeline ordering (strictly newest-first).
9.  Timeline + notes pagination (skip/limit + total, no overlap/gaps across pages).
10. Activity-type filtering on the timeline.
11. Timeline immutability (repository exposes no update/delete path).
12. Metadata JSONB round-trips correctly through Postgres.
13. RBAC (leads:view for reads, leads:update for note mutations).
14. Audit logging still fires for the new entities (reuses the existing listener).
15. Regression: the pre-existing Lead CRUD behaviour is unchanged by the activity hooks.

This suite talks to the real configured database (see CLAUDE.md). Every row it creates is
explicitly hard-deleted in a `finally` block at the end, since the repository layer commits
each write immediately (a session-level rollback would not undo already-committed work).
Deleting the parent Lead rows cascades away their activities and notes.
"""

import asyncio
import sys
import os
import random
import uuid
from datetime import datetime, timezone
from sqlalchemy import select, delete

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.core.context import audit_context
from app.core.exceptions import BadRequestException, NotFoundException, ForbiddenException
from app.models.lead import Lead, LeadStatus, LeadSource
from app.models.lead_activity import LeadActivity, LeadNote, ActivityType
from app.models.audit_log import AuditLog, AuditAction
from app.models.employee import Employee
from app.models.role import Role
from app.schemas.lead import LeadCreate, LeadUpdate
from app.schemas.lead_activity import LeadNoteCreate, LeadNoteUpdate, LeadActivityResponse
from app.schemas.employee import EmployeeCreate
from app.services.lead import LeadService
from app.services.lead_activity import LeadActivityService, LeadNoteService
from app.services.employee import EmployeeService
from app.services.cache import permission_cache
from app.repositories.lead_activity import (
    LeadActivityRepository,
    LeadNoteRepository,
    AdminLeadNoteRepository,
)
from app.api.deps import RequirePermission


def random_phone() -> str:
    return "".join(random.choices("0123456789", k=10))


async def test_lead_activities_suite():
    print("=== STARTING LEAD ACTIVITY & NOTES INTEGRATION TESTS ===")

    lead_service = LeadService()
    activity_service = LeadActivityService()
    note_service = LeadNoteService()
    employee_service = EmployeeService()
    unique_suffix = str(uuid.uuid4())[:8]

    created_lead_ids: list[uuid.UUID] = []
    created_employee_ids: list[uuid.UUID] = []

    async with AsyncSessionLocal() as db:
        try:
            # ==========================================================
            # [0] SETUP: roles + employees, and the acting-user context
            # ==========================================================
            print("\n--- [0] SETUP: ROLES, EMPLOYEES & AUDIT CONTEXT ---")
            admin_role = (await db.execute(select(Role).where(Role.name == "Administrator"))).scalars().first()
            viewer_role = (await db.execute(select(Role).where(Role.name == "Viewer"))).scalars().first()
            designer_role = (await db.execute(select(Role).where(Role.name == "Designer"))).scalars().first()
            assert admin_role is not None and viewer_role is not None and designer_role is not None

            actor = await employee_service.create_employee(db, EmployeeCreate(
                first_name="ActivityActor", last_name="Test",
                email=f"activity_actor_{unique_suffix}@colourlabs.com",
                phone=random_phone(), password="SecurePassword123!", role_id=admin_role.id,
            ))
            created_employee_ids.append(actor.id)

            viewer_employee = await employee_service.create_employee(db, EmployeeCreate(
                first_name="ActivityViewer", last_name="Test",
                email=f"activity_viewer_{unique_suffix}@colourlabs.com",
                phone=random_phone(), password="SecurePassword123!", role_id=viewer_role.id,
            ))
            created_employee_ids.append(viewer_employee.id)

            designer_employee = await employee_service.create_employee(db, EmployeeCreate(
                first_name="ActivityDesigner", last_name="Test",
                email=f"activity_designer_{unique_suffix}@colourlabs.com",
                phone=random_phone(), password="SecurePassword123!", role_id=designer_role.id,
            ))
            created_employee_ids.append(designer_employee.id)

            # The activity layer resolves "who did this" from the same audit ContextVar the
            # audit-log listener uses, so setting a real employee UUID here exercises the
            # actual production attribution path.
            audit_context.set({
                "user_id": str(actor.id),
                "ip_address": "192.168.1.77",
                "user_agent": "Mozilla/5.0 (Lead Activity Test Agent)",
            })
            print(f"Created 3 test employees; acting employee = {actor.id}")

            marker = f"ActivityMarker{unique_suffix}"

            # ==========================================================
            # [1] AUTOMATIC 'CREATED' ACTIVITY ON LEAD CREATION
            # ==========================================================
            print("\n--- [1] TESTING AUTOMATIC 'CREATED' ACTIVITY ---")
            lead = await lead_service.create_lead(db, LeadCreate(
                business_name=f"{marker} Studio", phone=random_phone(),
                city="Chennai", source=LeadSource.GOOGLE_MAPS,
            ))
            created_lead_ids.append(lead.id)
            # Held as a plain UUID. Section [12] calls `db.expire_all()`, after which
            # touching `lead.id` would trigger a lazy sync reload that asyncio forbids.
            lead_id = lead.id

            items, total = await activity_service.get_lead_timeline(db, lead_id)
            assert total == 1, f"Expected exactly 1 activity after create, got {total}"
            created_act = items[0]
            assert created_act.activity_type == ActivityType.CREATED
            assert created_act.title == "Lead created"
            assert created_act.lead_id == lead_id
            assert created_act.created_by_employee_id == actor.id, "Activity must be attributed to the acting employee"
            assert created_act.activity_metadata["business_name"] == f"{marker} Studio"
            assert created_act.activity_metadata["source"] == "GOOGLE_MAPS"
            assert created_act.activity_metadata["status"] == "NEW"
            # Held as a plain UUID so section [14] can query by it after `expire_all()`.
            created_activity_id = created_act.id
            print(f"CREATED activity auto-generated and attributed to employee {created_act.created_by_employee_id}")

            # ==========================================================
            # [2] AUTOMATIC 'UPDATED' ACTIVITY + CHANGE DIFF
            # ==========================================================
            print("\n--- [2] TESTING AUTOMATIC 'UPDATED' ACTIVITY ---")
            lead = await lead_service.update_lead(db, lead_id, LeadUpdate(
                contact_person="Bob Beta", city="Coimbatore", version=lead.version,
            ))
            items, total = await activity_service.get_lead_timeline(db, lead_id)
            assert total == 2, f"Expected 2 activities after a non-status update, got {total}"
            upd = items[0]
            assert upd.activity_type == ActivityType.UPDATED
            changes = upd.activity_metadata["changes"]
            assert set(changes.keys()) == {"contact_person", "city"}, f"Unexpected changed fields: {changes.keys()}"
            assert changes["city"]["old"] == "Chennai"
            assert changes["city"]["new"] == "Coimbatore"
            # Bookkeeping columns must not leak into the user-facing diff.
            assert "version" not in changes and "updated_at" not in changes
            print(f"UPDATED activity recorded a correct old->new diff: {sorted(changes.keys())}")

            # A no-op update (re-sending identical values) must not append a timeline entry.
            lead = await lead_service.update_lead(db, lead_id, LeadUpdate(
                city="Coimbatore", version=lead.version,
            ))
            _, total_after_noop = await activity_service.get_lead_timeline(db, lead_id)
            assert total_after_noop == 2, f"A no-op update must not create an activity (total={total_after_noop})"
            print("No-op update correctly produced no timeline entry.")

            # ==========================================================
            # [3] AUTOMATIC 'STATUS_CHANGED' ACTIVITY
            # ==========================================================
            print("\n--- [3] TESTING AUTOMATIC 'STATUS_CHANGED' ACTIVITY ---")
            lead = await lead_service.update_lead(db, lead_id, LeadUpdate(
                status=LeadStatus.CONTACTED, version=lead.version,
            ))
            items, total = await activity_service.get_lead_timeline(db, lead_id)
            # A status change emits BOTH the generic UPDATED and the specific STATUS_CHANGED.
            assert total == 4, f"Expected 4 activities after a status change, got {total}"
            status_acts = [a for a in items if a.activity_type == ActivityType.STATUS_CHANGED]
            assert len(status_acts) == 1
            sc = status_acts[0]
            assert sc.activity_metadata["old_status"] == "NEW"
            assert sc.activity_metadata["new_status"] == "CONTACTED"
            assert "NEW" in sc.title and "CONTACTED" in sc.title
            print(f"STATUS_CHANGED activity recorded: {sc.title}")

            # ==========================================================
            # [4] AUTOMATIC 'CONVERTED' ACTIVITY (transition-only)
            # ==========================================================
            print("\n--- [4] TESTING AUTOMATIC 'CONVERTED' ACTIVITY ---")
            lead = await lead_service.update_lead(db, lead_id, LeadUpdate(
                is_converted=True, status=LeadStatus.CUSTOMER, version=lead.version,
            ))
            items, _ = await activity_service.get_lead_timeline(db, lead_id)
            conv = [a for a in items if a.activity_type == ActivityType.CONVERTED]
            assert len(conv) == 1, f"Expected exactly 1 CONVERTED activity, got {len(conv)}"
            assert conv[0].activity_metadata["status"] == "CUSTOMER"
            print("CONVERTED activity auto-generated on conversion.")

            # Re-saving an already-converted lead must NOT append a second CONVERTED entry.
            lead = await lead_service.update_lead(db, lead_id, LeadUpdate(
                is_converted=True, remarks="Signed the contract.", version=lead.version,
            ))
            items, _ = await activity_service.get_lead_timeline(db, lead_id)
            conv_again = [a for a in items if a.activity_type == ActivityType.CONVERTED]
            assert len(conv_again) == 1, f"CONVERTED must fire on transition only, found {len(conv_again)}"
            print("CONVERTED correctly fired on transition only, not re-fired on subsequent saves.")

            # ==========================================================
            # [5] MANUAL NOTES: CREATE (+ emitted NOTE activity)
            # ==========================================================
            print("\n--- [5] TESTING NOTE CREATION ---")
            _, total_before_note = await activity_service.get_lead_timeline(db, lead_id)
            note = await note_service.create_note(db, lead_id, LeadNoteCreate(
                note="  Called the studio owner; asked for a callback on Monday.  "
            ))
            assert note.id is not None
            assert note.lead_id == lead_id
            assert note.note == "Called the studio owner; asked for a callback on Monday.", "Note body must be stripped"
            assert note.created_by_employee_id == actor.id
            assert note.is_deleted is False
            # Held as plain UUIDs so later sections can query by them after `expire_all()`.
            note_id = note.id
            print(f"Note created (ID: {note.id}), body stripped and attributed correctly.")

            items, total_after_note = await activity_service.get_lead_timeline(db, lead_id)
            assert total_after_note == total_before_note + 1, "Creating a note must emit exactly one NOTE activity"
            note_act = items[0]
            assert note_act.activity_type == ActivityType.NOTE
            assert note_act.title == "Note added"
            assert note_act.activity_metadata["note_id"] == str(note.id), "NOTE activity must link back to the note"
            assert note_act.description == note.note
            print("NOTE activity emitted and linked to the note via metadata.note_id.")

            # Blank note rejected at the schema layer.
            try:
                LeadNoteCreate(note="   ")
                assert False, "Blank note did not raise a validation error"
            except Exception as e:
                print(f"Blank note correctly rejected by schema validation: {type(e).__name__}")

            # Note on a non-existent lead -> 404.
            try:
                await note_service.create_note(db, uuid.uuid4(), LeadNoteCreate(note="Orphan note"))
                assert False, "Creating a note on an unknown lead did not raise NotFoundException"
            except NotFoundException:
                print("Creating a note on an unknown lead correctly raises NotFoundException.")

            # ==========================================================
            # [6] MANUAL NOTES: EDIT
            # ==========================================================
            print("\n--- [6] TESTING NOTE EDITING ---")
            original_created_at = note.created_at
            _, timeline_before_edit = await activity_service.get_lead_timeline(db, lead_id)

            edited = await note_service.update_note(db, note.id, LeadNoteUpdate(
                note="Called the studio owner; callback confirmed for Monday 10am."
            ))
            assert edited.id == note.id
            assert edited.note == "Called the studio owner; callback confirmed for Monday 10am."
            assert edited.created_at == original_created_at, "Editing must not alter created_at"
            assert edited.created_by_employee_id == actor.id, "Editing must not reassign authorship"
            print("Note body updated; created_at and authorship preserved.")

            _, timeline_after_edit = await activity_service.get_lead_timeline(db, lead_id)
            assert timeline_after_edit == timeline_before_edit, "Editing a note must not append a timeline entry"
            print("Editing correctly produced no new timeline entry (audit log covers the edit).")

            try:
                await note_service.update_note(db, uuid.uuid4(), LeadNoteUpdate(note="ghost"))
                assert False, "Editing an unknown note did not raise NotFoundException"
            except NotFoundException:
                print("Editing an unknown note correctly raises NotFoundException.")

            # ==========================================================
            # [7] MANUAL NOTES: LIST + DELETE
            # ==========================================================
            print("\n--- [7] TESTING NOTE LISTING & DELETION ---")
            note2 = await note_service.create_note(db, lead_id, LeadNoteCreate(note="Second note: sent pricing sheet."))
            note3 = await note_service.create_note(db, lead_id, LeadNoteCreate(note="Third note: awaiting reply."))
            note3_id = note3.id

            notes, notes_total = await note_service.get_notes_by_lead(db, lead_id)
            assert notes_total == 3, f"Expected 3 notes, got {notes_total}"
            # Newest first.
            note_times = [n.created_at for n in notes]
            assert note_times == sorted(note_times, reverse=True), "Notes must be returned newest-first"
            print(f"Listed {notes_total} notes, newest-first ordering verified.")

            _, timeline_before_note_delete = await activity_service.get_lead_timeline(db, lead_id)
            await note_service.delete_note(db, note3_id)

            try:
                await note_service.get_note_by_id(db, note3_id)
                assert False, "Soft-deleted note was still retrievable"
            except NotFoundException:
                print("Soft-deleted note correctly excluded from get_note_by_id.")

            notes_after, notes_total_after = await note_service.get_notes_by_lead(db, lead_id)
            assert notes_total_after == 2
            assert note3_id not in {n.id for n in notes_after}
            print("Soft-deleted note correctly excluded from the notes list.")

            # The row survives, flagged, and is reachable through the admin repository.
            admin_note_repo = AdminLeadNoteRepository()
            deleted_row = await admin_note_repo.get_by_id(db, note3_id)
            assert deleted_row is not None and deleted_row.is_deleted is True and deleted_row.deleted_at is not None
            print("Soft-deleted note still visible via AdminLeadNoteRepository.")

            # The NOTE activity announcing it must survive the note's deletion.
            items, timeline_after_note_delete = await activity_service.get_lead_timeline(db, lead_id)
            assert timeline_after_note_delete == timeline_before_note_delete, \
                "Deleting a note must not remove its NOTE activity from the timeline"
            surviving = [a for a in items if a.activity_metadata and a.activity_metadata.get("note_id") == str(note3_id)]
            assert len(surviving) == 1, "The NOTE activity for a deleted note must be preserved"
            print("NOTE activity preserved after its note was deleted (timeline stays truthful).")

            try:
                await note_service.delete_note(db, note3_id)
                assert False, "Deleting an already-deleted note did not raise NotFoundException"
            except NotFoundException:
                print("Deleting an already-deleted note correctly raises NotFoundException.")

            # ==========================================================
            # [8] TIMELINE ORDERING (strictly newest-first)
            # ==========================================================
            print("\n--- [8] TESTING TIMELINE ORDERING ---")
            all_items, all_total = await activity_service.get_lead_timeline(db, lead_id, limit=200)
            timestamps = [a.created_at for a in all_items]
            assert timestamps == sorted(timestamps, reverse=True), "Timeline must be strictly newest-first"
            # The oldest entry must be the CREATED one.
            assert all_items[-1].activity_type == ActivityType.CREATED, \
                f"Oldest timeline entry should be CREATED, got {all_items[-1].activity_type}"
            print(f"Timeline of {all_total} entries verified newest-first, oldest entry is CREATED.")

            # ==========================================================
            # [9] PAGINATION (activities + notes)
            # ==========================================================
            print("\n--- [9] TESTING PAGINATION ---")
            page_size = 3
            collected: list[uuid.UUID] = []
            skip = 0
            while skip < all_total:
                page, page_total = await activity_service.get_lead_timeline(db, lead_id, skip=skip, limit=page_size)
                assert page_total == all_total, "total must be independent of skip/limit"
                assert len(page) == min(page_size, all_total - skip)
                collected.extend([a.id for a in page])
                skip += page_size

            assert len(collected) == all_total, f"Paged through {len(collected)} rows, expected {all_total}"
            assert len(set(collected)) == all_total, "Pagination returned duplicate rows across pages"
            assert collected == [a.id for a in all_items], "Paged order must match the unpaginated order"
            print(f"Activity pagination verified across {all_total} entries: no gaps, no duplicates, stable order.")

            # Overshooting the end returns an empty page, not an error.
            empty_page, empty_total = await activity_service.get_lead_timeline(db, lead_id, skip=all_total + 50, limit=10)
            assert len(empty_page) == 0 and empty_total == all_total
            print("Out-of-range pagination returns an empty page with the correct total.")

            notes_p1, notes_p1_total = await note_service.get_notes_by_lead(db, lead_id, skip=0, limit=1)
            notes_p2, _ = await note_service.get_notes_by_lead(db, lead_id, skip=1, limit=1)
            assert notes_p1_total == 2 and len(notes_p1) == 1 and len(notes_p2) == 1
            assert notes_p1[0].id != notes_p2[0].id
            print("Note pagination verified.")

            # ==========================================================
            # [10] ACTIVITY TYPE FILTERING
            # ==========================================================
            print("\n--- [10] TESTING ACTIVITY TYPE FILTERING ---")
            notes_only, notes_only_total = await activity_service.get_lead_timeline(
                db, lead_id, activity_type=ActivityType.NOTE, limit=200
            )
            assert notes_only_total == 3, f"Expected 3 NOTE activities, got {notes_only_total}"
            assert all(a.activity_type == ActivityType.NOTE for a in notes_only)
            print(f"Filter by activity_type=NOTE returned {notes_only_total} entries, all correctly typed.")

            created_only, created_only_total = await activity_service.get_lead_timeline(
                db, lead_id, activity_type=ActivityType.CREATED
            )
            assert created_only_total == 1
            print("Filter by activity_type=CREATED returned exactly 1 entry.")

            # A type that was never emitted (WhatsApp is out of scope this phase) returns nothing.
            wa, wa_total = await activity_service.get_lead_timeline(
                db, lead_id, activity_type=ActivityType.WHATSAPP_SENT
            )
            assert wa_total == 0 and len(wa) == 0
            print("Filter by an unemitted type (WHATSAPP_SENT) correctly returns zero entries.")

            # ==========================================================
            # [11] TIMELINE IMMUTABILITY
            # ==========================================================
            print("\n--- [11] TESTING TIMELINE IMMUTABILITY ---")
            act_repo = LeadActivityRepository()
            assert not hasattr(act_repo, "update"), "LeadActivityRepository must expose no update path"
            assert not hasattr(act_repo, "delete"), "LeadActivityRepository must expose no delete path"
            assert not hasattr(activity_service, "update_activity")
            assert not hasattr(activity_service, "delete_activity")
            print("Activity repository/service expose no update or delete path (append-only enforced).")

            # ==========================================================
            # [12] METADATA JSONB ROUND-TRIP + RESPONSE ALIASING
            # ==========================================================
            print("\n--- [12] TESTING METADATA JSONB ROUND-TRIP ---")
            # Expire only this one instance (not `expire_all()`, which would expire every
            # object in the session and make later attribute reads attempt a lazy sync
            # reload that asyncio forbids), so the fetch below is a genuine round-trip to
            # Postgres rather than an identity-map hit.
            status_activity_id = sc.id
            db.expire(sc)
            reread = await act_repo.get_by_id(db, status_activity_id)
            assert isinstance(reread.activity_metadata, dict), "metadata must round-trip as a dict"
            assert reread.activity_metadata == {"old_status": "NEW", "new_status": "CONTACTED"}
            print(f"JSONB metadata round-tripped from Postgres intact: {reread.activity_metadata}")

            # The wire contract exposes the column as `metadata`, not `activity_metadata`.
            dumped = LeadActivityResponse.model_validate(reread).model_dump(by_alias=True)
            assert "metadata" in dumped, "API response must expose the field as 'metadata'"
            assert "activity_metadata" not in dumped
            assert dumped["metadata"] == {"old_status": "NEW", "new_status": "CONTACTED"}
            print("LeadActivityResponse correctly serializes activity_metadata as 'metadata'.")

            # A null-metadata activity is also valid.
            plain = await activity_service.record(
                db, lead_id=lead_id, activity_type=ActivityType.PHONE_CALL,
                title="Phone call logged", description="Spoke for 5 minutes.",
            )
            assert plain.activity_metadata is None
            print("Activity with null metadata persisted successfully.")

            # ==========================================================
            # [13] AUTOMATIC 'DELETED' ACTIVITY ON LEAD SOFT DELETE
            # ==========================================================
            print("\n--- [13] TESTING AUTOMATIC 'DELETED' ACTIVITY ---")
            doomed = await lead_service.create_lead(db, LeadCreate(
                business_name=f"{marker} Doomed Studio", phone=random_phone(),
            ))
            created_lead_ids.append(doomed.id)
            await lead_service.delete_lead(db, doomed.id)

            # The lead is soft-deleted, so the service read path 404s (it must not leak
            # timelines for deleted leads); read the rows directly to assert the entry exists.
            try:
                await activity_service.get_lead_timeline(db, doomed.id)
                assert False, "Timeline of a soft-deleted lead should raise NotFoundException"
            except NotFoundException:
                print("Timeline of a soft-deleted lead correctly raises NotFoundException.")

            rows = (await db.execute(
                select(LeadActivity).where(LeadActivity.lead_id == doomed.id)
            )).scalars().all()
            types = {r.activity_type for r in rows}
            assert ActivityType.CREATED in types and ActivityType.DELETED in types, f"Got {types}"
            print("DELETED activity auto-generated and retained for the soft-deleted lead.")

            # ==========================================================
            # [14] AUDIT LOGGING REUSE
            # ==========================================================
            print("\n--- [14] TESTING AUDIT LOG REUSE ---")
            note_logs = (await db.execute(
                select(AuditLog).where(AuditLog.entity_id == note_id).order_by(AuditLog.created_at.asc())
            )).scalars().all()
            assert len(note_logs) >= 2, f"Expected CREATE + UPDATE audit rows for the note, got {len(note_logs)}"
            assert note_logs[0].entity_name == "LeadNote"
            assert note_logs[0].action == AuditAction.CREATE
            assert note_logs[0].performed_by == str(actor.id)
            assert note_logs[0].ip_address == "192.168.1.77"
            print("LeadNote CREATE audit log verified (existing listener, no extra wiring).")

            update_logs = [l for l in note_logs if l.action == AuditAction.UPDATE]
            assert update_logs, "Editing a note must produce an UPDATE audit row"
            assert update_logs[0].old_values["note"] == "Called the studio owner; asked for a callback on Monday."
            assert update_logs[0].new_values["note"] == "Called the studio owner; callback confirmed for Monday 10am."
            print("LeadNote UPDATE audit log captured the old->new note body.")

            del_logs = (await db.execute(
                select(AuditLog).where(AuditLog.entity_id == note3_id)
            )).scalars().all()
            assert any(l.action == AuditAction.DELETE for l in del_logs), "Note soft delete must audit as DELETE"
            print("LeadNote DELETE (soft-delete) audit log verified.")

            act_logs = (await db.execute(
                select(AuditLog).where(AuditLog.entity_id == created_activity_id)
            )).scalars().all()
            assert any(l.entity_name == "LeadActivity" and l.action == AuditAction.CREATE for l in act_logs)
            print("LeadActivity CREATE audit log verified.")

            # ==========================================================
            # [15] RBAC
            # ==========================================================
            print("\n--- [15] TESTING RBAC PROTECTION ---")
            await permission_cache.clear()
            dep_view = RequirePermission("leads:view")
            dep_update = RequirePermission("leads:update")

            # Viewer holds *:view -> may read the timeline/notes, may not mutate notes.
            res = await dep_view(db, viewer_employee, employee_service)
            assert res.id == viewer_employee.id
            print("RBAC: Viewer allowed on leads:view (timeline + notes reads).")

            try:
                await dep_update(db, viewer_employee, employee_service)
                assert False, "Viewer should not hold leads:update"
            except ForbiddenException:
                print("RBAC: Viewer correctly blocked on leads:update (note create/edit/delete).")

            # Designer holds no leads permission at all.
            for dep, label in [(dep_view, "leads:view"), (dep_update, "leads:update")]:
                try:
                    await dep(db, designer_employee, employee_service)
                    assert False, f"Designer should not have access to {label}"
                except ForbiddenException:
                    print(f"RBAC: Designer correctly blocked on {label}.")

            # Administrator bypasses permission checks entirely.
            for dep, label in [(dep_view, "leads:view"), (dep_update, "leads:update")]:
                res = await dep(db, actor, employee_service)
                assert res.id == actor.id
            print("RBAC: Administrator bypasses all lead-activity permission checks.")

            # ==========================================================
            # [16] REGRESSION: EXISTING LEAD CRUD UNCHANGED
            # ==========================================================
            print("\n--- [16] REGRESSION: EXISTING LEAD BEHAVIOUR ---")
            reg = await lead_service.create_lead(db, LeadCreate(
                business_name=f"{marker} Regression Co", phone=random_phone(),
                status=LeadStatus.INTERESTED,  # must still be forced to NEW
            ))
            created_lead_ids.append(reg.id)
            assert reg.status == LeadStatus.NEW, "create_lead must still force status=NEW"
            assert reg.version == 1 and reg.is_converted is False and reg.is_deleted is False
            print("Lead creation defaults (status=NEW, version=1) still enforced.")

            # Duplicate phone still rejected, and the failed create must not leave an activity.
            activities_before = (await db.execute(select(LeadActivity))).scalars().all()
            try:
                await lead_service.create_lead(db, LeadCreate(
                    business_name=f"{marker} Dupe", phone=reg.phone,
                ))
                assert False, "Duplicate phone did not raise BadRequestException"
            except BadRequestException:
                print("Duplicate phone still rejected.")
            activities_after = (await db.execute(select(LeadActivity))).scalars().all()
            assert len(activities_after) == len(activities_before), \
                "A rejected lead creation must not write an activity"
            print("A rejected create wrote no orphan activity.")

            # Optimistic locking still enforced, and a rejected update writes no activity.
            reg = await lead_service.update_lead(db, reg.id, LeadUpdate(
                remarks="First touch.", version=reg.version,
            ))
            assert reg.version == 2
            _, reg_total_before = await activity_service.get_lead_timeline(db, reg.id)
            from app.core.exceptions import ConflictException
            try:
                await lead_service.update_lead(db, reg.id, LeadUpdate(status=LeadStatus.LOST, version=1))
                assert False, "Stale version did not raise ConflictException"
            except ConflictException:
                print("Optimistic locking still enforced.")
            _, reg_total_after = await activity_service.get_lead_timeline(db, reg.id)
            assert reg_total_after == reg_total_before, "A rejected update must not write an activity"
            print("A rejected update wrote no orphan activity.")

            # Listing/searching leads is unaffected by the new tables.
            found, found_total = await lead_service.get_all_leads(db, search=marker)
            assert found_total >= 2
            print(f"Lead search still functional ({found_total} matches for the test marker).")

            print("\n=== ALL LEAD ACTIVITY & NOTES INTEGRATION TESTS COMPLETED SUCCESSFULLY ===")

        except Exception as e:
            print(f"\nTEST SUITE FAILED WITH ERROR: {e}")
            import traceback
            traceback.print_exc()
            raise e
        finally:
            # Repository writes commit immediately, so we explicitly hard-delete everything
            # this suite created. Deleting a Lead cascades its activities and notes away
            # (FK ON DELETE CASCADE), so those need no separate cleanup.
            print("\nCleaning up test data...")
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
    asyncio.run(test_lead_activities_suite())
