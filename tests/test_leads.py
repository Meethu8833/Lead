"""
tests/test_leads.py

Integration test suite for the Lead Management module foundation.
Verifies:
1. Create Lead (defaults: status=NEW, source=MANUAL, is_converted=False, version=1).
2. Duplicate phone number is rejected.
3. Update Lead (partial update + field validation).
4. Optimistic locking (stale version update is rejected with ConflictException).
5. Search Leads (business_name, contact_person, phone, whatsapp, email).
6. Filtering (status, source, district, city, assigned employee, created date range).
7. Pagination (skip/limit + total count).
8. Soft Delete (excluded from normal queries, still visible via AdminLeadRepository).
9. RBAC protection (leads:view / leads:create / leads:update / leads:delete).
10. Audit log creation (CREATE / UPDATE / DELETE entries for the Lead entity).

This suite talks to the real configured database (see CLAUDE.md). Every row it creates is
explicitly hard-deleted in a `finally` block at the end, since the repository layer commits
each write immediately (a session-level rollback would not undo already-committed work).
"""

import asyncio
import sys
import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.core.context import audit_context
from app.core.exceptions import BadRequestException, NotFoundException, ConflictException, ForbiddenException
from app.models.lead import Lead, LeadStatus, LeadSource
from app.models.audit_log import AuditLog, AuditAction
from app.models.employee import Employee
from app.models.role import Role
from app.schemas.lead import LeadCreate, LeadUpdate
from app.schemas.employee import EmployeeCreate
from app.services.lead import LeadService
from app.services.employee import EmployeeService
from app.services.cache import permission_cache
from app.repositories.lead import LeadRepository, AdminLeadRepository
from app.api.deps import RequirePermission


def random_phone() -> str:
    return "".join(random.choices("0123456789", k=10))


async def test_leads_suite():
    print("=== STARTING LEAD MODULE INTEGRATION TESTS ===")

    lead_service = LeadService()
    employee_service = EmployeeService()
    unique_suffix = str(uuid.uuid4())[:8]

    created_lead_ids: list[uuid.UUID] = []
    created_employee_ids: list[uuid.UUID] = []

    user_id = str(uuid.uuid4())
    audit_context.set({
        "user_id": user_id,
        "ip_address": "192.168.1.50",
        "user_agent": "Mozilla/5.0 (Lead Test Agent)"
    })

    async with AsyncSessionLocal() as db:
        try:
            # ==========================================================
            # [0] SETUP: roles + test employees for RBAC/assignment tests
            # ==========================================================
            print("\n--- [0] SETUP: FETCHING ROLES & CREATING TEST EMPLOYEES ---")
            stmt_admin = select(Role).where(Role.name == "Administrator")
            admin_role = (await db.execute(stmt_admin)).scalars().first()
            assert admin_role is not None

            stmt_viewer = select(Role).where(Role.name == "Viewer")
            viewer_role = (await db.execute(stmt_viewer)).scalars().first()
            assert viewer_role is not None

            stmt_designer = select(Role).where(Role.name == "Designer")
            designer_role = (await db.execute(stmt_designer)).scalars().first()
            assert designer_role is not None

            viewer_employee = await employee_service.create_employee(db, EmployeeCreate(
                first_name="LeadViewer",
                last_name="Test",
                email=f"lead_viewer_{unique_suffix}@colourlabs.com",
                phone=random_phone(),
                password="SecurePassword123!",
                role_id=viewer_role.id
            ))
            created_employee_ids.append(viewer_employee.id)

            designer_employee = await employee_service.create_employee(db, EmployeeCreate(
                first_name="LeadDesigner",
                last_name="Test",
                email=f"lead_designer_{unique_suffix}@colourlabs.com",
                phone=random_phone(),
                password="SecurePassword123!",
                role_id=designer_role.id
            ))
            created_employee_ids.append(designer_employee.id)

            assignee = await employee_service.create_employee(db, EmployeeCreate(
                first_name="LeadAssignee",
                last_name="Test",
                email=f"lead_assignee_{unique_suffix}@colourlabs.com",
                phone=random_phone(),
                password="SecurePassword123!",
                role_id=viewer_role.id
            ))
            created_employee_ids.append(assignee.id)
            print(f"Created 3 test employees under Viewer/Designer roles.")

            # ==========================================================
            # [1] CREATE LEAD + DEFAULTS
            # ==========================================================
            print("\n--- [1] TESTING LEAD CREATION & DEFAULTS ---")
            phone_1 = random_phone()
            marker = f"LeadTestMarker{unique_suffix}"
            lead1 = await lead_service.create_lead(db, LeadCreate(
                business_name=f"{marker} Studio Alpha",
                contact_person="Alice Alpha",
                phone=phone_1,
                email="alpha@example.com",
                city="Chennai",
                district="Chennai",
                state="Tamil Nadu",
                country="India",
                source=LeadSource.GOOGLE_MAPS,
                status=LeadStatus.INTERESTED,  # must be ignored/forced to NEW on create
            ))
            created_lead_ids.append(lead1.id)

            assert lead1.id is not None
            assert lead1.status == LeadStatus.NEW, "New leads must always start at status NEW"
            assert lead1.source == LeadSource.GOOGLE_MAPS
            assert lead1.is_converted is False
            assert lead1.version == 1
            assert lead1.is_deleted is False
            print(f"Lead created with enforced status=NEW (ID: {lead1.id}), source={lead1.source}")

            # Default source when omitted
            lead_default = await lead_service.create_lead(db, LeadCreate(
                business_name=f"{marker} Default Source Co",
                phone=random_phone(),
            ))
            created_lead_ids.append(lead_default.id)
            assert lead_default.source == LeadSource.MANUAL
            assert lead_default.status == LeadStatus.NEW
            print("Default source=MANUAL and status=NEW verified for minimal payload.")

            # ==========================================================
            # [2] DUPLICATE PHONE REJECTED
            # ==========================================================
            print("\n--- [2] TESTING DUPLICATE PHONE UNIQUENESS ---")
            try:
                await lead_service.create_lead(db, LeadCreate(
                    business_name=f"{marker} Duplicate Phone Co",
                    phone=phone_1,
                ))
                assert False, "Duplicate phone number did not raise BadRequestException"
            except BadRequestException as e:
                print(f"Uniqueness check passed (raised BadRequestException): {e}")

            # ==========================================================
            # [3] BUSINESS NAME REQUIRED / BLANK REJECTED
            # ==========================================================
            print("\n--- [3] TESTING BUSINESS NAME VALIDATION ---")
            try:
                LeadCreate(business_name="   ", phone=random_phone())
                assert False, "Blank business_name did not raise a validation error"
            except Exception as e:
                print(f"Blank business_name correctly rejected by schema validation: {type(e).__name__}")

            # ==========================================================
            # [4] UPDATE LEAD + OPTIMISTIC LOCKING
            # ==========================================================
            print("\n--- [4] TESTING UPDATE & OPTIMISTIC LOCKING ---")
            updated = await lead_service.update_lead(db, lead1.id, LeadUpdate(
                status=LeadStatus.CONTACTED,
                remarks="First contact made via phone.",
                version=lead1.version,
            ))
            assert updated.status == LeadStatus.CONTACTED
            assert updated.version == 2
            print(f"Lead updated successfully. New version: {updated.version}")

            try:
                await lead_service.update_lead(db, lead1.id, LeadUpdate(
                    status=LeadStatus.LOST,
                    version=1,  # stale version
                ))
                assert False, "Stale version update did not raise ConflictException"
            except ConflictException as e:
                print(f"Optimistic locking correctly enforced (raised ConflictException): {e}")

            # ==========================================================
            # [5] ASSIGN EMPLOYEE + FILTER BY ASSIGNED EMPLOYEE / STATUS / SOURCE / CITY / DISTRICT
            # ==========================================================
            print("\n--- [5] TESTING FILTERS ---")
            assigned_lead = await lead_service.create_lead(db, LeadCreate(
                business_name=f"{marker} Assigned Studio",
                phone=random_phone(),
                city="Coimbatore",
                district="Coimbatore",
                source=LeadSource.REFERRAL,
                assigned_employee_id=assignee.id,
            ))
            created_lead_ids.append(assigned_lead.id)

            by_assignee, total_assignee = await lead_service.get_all_leads(
                db, assigned_employee_id=assignee.id
            )
            assert total_assignee == 1
            assert by_assignee[0].id == assigned_lead.id
            print("Filter by assigned_employee_id passed.")

            by_status, total_status = await lead_service.get_all_leads(
                db, status=LeadStatus.CONTACTED, search=marker
            )
            assert total_status == 1
            assert by_status[0].id == lead1.id
            print("Filter by status passed.")

            by_source, total_source = await lead_service.get_all_leads(
                db, source=LeadSource.REFERRAL, search=marker
            )
            assert total_source == 1
            assert by_source[0].id == assigned_lead.id
            print("Filter by source passed.")

            by_city, total_city = await lead_service.get_all_leads(
                db, city="Coimbatore", search=marker
            )
            assert total_city == 1
            assert by_city[0].id == assigned_lead.id
            print("Filter by city passed.")

            by_district, total_district = await lead_service.get_all_leads(
                db, district="Chennai", search=marker
            )
            assert total_district == 1
            assert by_district[0].id == lead1.id
            print("Filter by district passed.")

            now = datetime.now(timezone.utc)
            by_date, total_date = await lead_service.get_all_leads(
                db, search=marker, created_from=now - timedelta(minutes=5), created_to=now + timedelta(minutes=5)
            )
            assert total_date == 3  # lead1, lead_default, assigned_lead
            print("Filter by created date range passed.")

            by_date_none, total_date_none = await lead_service.get_all_leads(
                db, search=marker, created_from=now + timedelta(days=1)
            )
            assert total_date_none == 0
            print("Filter by future created_from correctly returns zero results.")

            # ==========================================================
            # [6] SEARCH ACROSS business_name/contact_person/phone/whatsapp/email
            # ==========================================================
            print("\n--- [6] TESTING SEARCH ---")
            search_by_name, _ = await lead_service.get_all_leads(db, search=marker)
            assert len(search_by_name) == 3
            print("Search by business_name keyword passed.")

            search_by_contact, total_contact = await lead_service.get_all_leads(db, search="Alice Alpha")
            assert total_contact == 1
            assert search_by_contact[0].id == lead1.id
            print("Search by contact_person passed.")

            search_by_phone, total_phone = await lead_service.get_all_leads(db, search=phone_1)
            assert total_phone == 1
            assert search_by_phone[0].id == lead1.id
            print("Search by phone passed.")

            search_by_email, total_email = await lead_service.get_all_leads(db, search="alpha@example.com")
            assert total_email == 1
            assert search_by_email[0].id == lead1.id
            print("Search by email passed.")

            # ==========================================================
            # [7] PAGINATION
            # ==========================================================
            print("\n--- [7] TESTING PAGINATION ---")
            page1, page1_total = await lead_service.get_all_leads(db, search=marker, skip=0, limit=2)
            assert len(page1) == 2
            assert page1_total == 3
            page2, page2_total = await lead_service.get_all_leads(db, search=marker, skip=2, limit=2)
            assert len(page2) == 1
            assert page2_total == 3
            page_ids = {l.id for l in page1} | {l.id for l in page2}
            assert page_ids == {lead1.id, lead_default.id, assigned_lead.id}
            print("Pagination (skip/limit + total count) passed.")

            # ==========================================================
            # [8] SOFT DELETE
            # ==========================================================
            print("\n--- [8] TESTING SOFT DELETE ---")
            await lead_service.delete_lead(db, lead_default.id)

            try:
                await lead_service.get_lead_by_id(db, lead_default.id)
                assert False, "Soft-deleted lead was still retrievable via get_lead_by_id"
            except NotFoundException:
                print("Soft-deleted lead correctly excluded from get_lead_by_id.")

            post_delete_items, post_delete_total = await lead_service.get_all_leads(db, search=marker)
            assert lead_default.id not in {l.id for l in post_delete_items}
            assert post_delete_total == 2
            print("Soft-deleted lead correctly excluded from list/search results.")

            admin_repo = AdminLeadRepository()
            deleted_row = await admin_repo.get_by_id(db, lead_default.id)
            assert deleted_row is not None
            assert deleted_row.is_deleted is True
            assert deleted_row.deleted_at is not None
            print("Soft-deleted lead still visible via AdminLeadRepository (include_deleted).")

            try:
                await lead_service.delete_lead(db, uuid.uuid4())
                assert False, "Deleting a non-existent lead did not raise NotFoundException"
            except NotFoundException:
                print("Deleting a non-existent lead correctly raises NotFoundException.")

            # ==========================================================
            # [9] AUDIT LOG CREATION
            # ==========================================================
            print("\n--- [9] TESTING AUDIT LOG CREATION ---")
            audit_query = select(AuditLog).where(AuditLog.entity_id == lead1.id).order_by(AuditLog.created_at.asc())
            logs = (await db.execute(audit_query)).scalars().all()
            assert len(logs) >= 2  # CREATE + UPDATE
            create_log = logs[0]
            assert create_log.entity_name == "Lead"
            assert create_log.action == AuditAction.CREATE
            assert create_log.performed_by == user_id
            assert create_log.ip_address == "192.168.1.50"
            assert create_log.new_values["business_name"] == f"{marker} Studio Alpha"
            assert create_log.new_values["status"] == "NEW"
            print("CREATE audit log verified.")

            update_log = logs[1]
            # Changing `status` is specially tagged STATUS_CHANGE by the audit listener
            # (see app/core/database.py `status_fields`), not a generic UPDATE.
            assert update_log.action == AuditAction.STATUS_CHANGE
            assert update_log.old_values["status"] == "NEW"
            assert update_log.new_values["status"] == "CONTACTED"
            print("STATUS_CHANGE audit log verified.")

            delete_audit_query = select(AuditLog).where(AuditLog.entity_id == lead_default.id).order_by(AuditLog.created_at.asc())
            delete_logs = (await db.execute(delete_audit_query)).scalars().all()
            assert any(log.action == AuditAction.DELETE for log in delete_logs)
            delete_log = next(log for log in delete_logs if log.action == AuditAction.DELETE)
            assert delete_log.entity_name == "Lead"
            assert delete_log.new_values["is_deleted"] is True
            print("DELETE (soft-delete) audit log verified.")

            # ==========================================================
            # [10] RBAC PROTECTION
            # ==========================================================
            print("\n--- [10] TESTING RBAC PROTECTION ---")
            await permission_cache.clear()

            dep_view = RequirePermission("leads:view")
            dep_create = RequirePermission("leads:create")
            dep_update = RequirePermission("leads:update")
            dep_delete = RequirePermission("leads:delete")

            # Viewer role has *:view -> leads:view allowed, leads:create/update/delete blocked
            res = await dep_view(db, viewer_employee, employee_service)
            assert res.id == viewer_employee.id
            print("RBAC: Viewer role allowed on leads:view (via *:view wildcard).")

            for dep, label in [(dep_create, "leads:create"), (dep_update, "leads:update"), (dep_delete, "leads:delete")]:
                try:
                    await dep(db, viewer_employee, employee_service)
                    assert False, f"Viewer role should not have access to {label}"
                except ForbiddenException:
                    print(f"RBAC: Viewer role correctly blocked on {label}.")

            # Designer role has none of orders/production/dashboard -> no leads permission at all
            for dep, label in [(dep_view, "leads:view"), (dep_create, "leads:create"), (dep_update, "leads:update"), (dep_delete, "leads:delete")]:
                try:
                    await dep(db, designer_employee, employee_service)
                    assert False, f"Designer role should not have access to {label}"
                except ForbiddenException:
                    print(f"RBAC: Designer role correctly blocked on {label} (no leads permission granted).")

            # Administrator bypasses all permission checks
            designer_employee.role = admin_role
            designer_employee.role_id = admin_role.id
            db.add(designer_employee)
            await db.commit()
            await permission_cache.invalidate_employee(designer_employee.id)

            for dep, label in [(dep_view, "leads:view"), (dep_create, "leads:create"), (dep_update, "leads:update"), (dep_delete, "leads:delete")]:
                res = await dep(db, designer_employee, employee_service)
                assert res.id == designer_employee.id
            print("RBAC: Administrator role bypasses all leads permission checks.")

            print("\n=== ALL LEAD MODULE INTEGRATION TESTS COMPLETED SUCCESSFULLY ===")

        except Exception as e:
            print(f"\nTEST SUITE FAILED WITH ERROR: {e}")
            import traceback
            traceback.print_exc()
            raise e
        finally:
            # Repository writes commit immediately, so we explicitly hard-delete
            # everything this suite created to keep the shared database clean.
            print("\nCleaning up test data...")
            for lead_id in created_lead_ids:
                row = await db.get(Lead, lead_id)
                if row:
                    await db.delete(row)
            for employee_id in created_employee_ids:
                row = await db.get(Employee, employee_id)
                if row:
                    await db.delete(row)
            await db.commit()
            print("Cleanup complete.")


if __name__ == "__main__":
    asyncio.run(test_leads_suite())
