"""
tests/test_permissions.py

Integration tests for the Permission Cache, Wildcards, and Concurrency-safe Sequence.
Verifies:
1. Cache Hits and Cache Misses behavior.
2. Wildcard Permission Matching (orders:view matches orders:* or *:*).
3. Employee role update or deactivation invalidates cached permissions.
4. Concurrent Employee Registration generates unique, sequential codes without conflict.
"""

import asyncio
import sys
import os
import uuid
from sqlalchemy import select
from sqlalchemy.orm import selectinload

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.models.employee import Employee
from app.models.role import Role
from app.models.permission import Permission
from app.schemas.employee import EmployeeCreate, EmployeeUpdate
from app.services.employee import EmployeeService
from app.services.cache import permission_cache
from app.api.deps import RequirePermission


async def test_permissions_suite():
    print("=== STARTING PERMISSION HARDENING & CONCURRENCY INTEGRATION TESTS ===")

    employee_service = EmployeeService()

    async with AsyncSessionLocal() as db:
        try:
            # Clear permission cache first
            await permission_cache.clear()

            # 1. SETUP ROLES AND TEST EMPLOYEE
            print("\n--- [1] SETTING UP TEST ROLES & EMPLOYEE ---")
            
            # Fetch default Viewer and Admin roles seeded by migration
            stmt_admin = select(Role).where(Role.name == "Administrator")
            res_admin = await db.execute(stmt_admin)
            admin_role = res_admin.scalars().first()
            assert admin_role is not None

            stmt_viewer = select(Role).where(Role.name == "Viewer")
            res_viewer = await db.execute(stmt_viewer)
            viewer_role = res_viewer.scalars().first()
            assert viewer_role is not None

            import random
            unique_id = str(uuid.uuid4())[:8]
            email = f"perm_test_{unique_id}@colourlabs.com"
            phone = "".join(random.choices("0123456789", k=10))
            
            create_schema = EmployeeCreate(

                first_name="Perm",
                last_name="Test",
                email=email,
                phone=phone,
                password="SecurePassword123!",
                role_id=viewer_role.id
            )
            employee = await employee_service.create_employee(db, create_schema)
            assert employee.id is not None
            print(f"Test employee created under role 'Viewer' (ID: {employee.id})")

            # 2. TEST CACHE MISS AND CACHE HIT
            print("\n--- [2] TESTING CACHE MISS & CACHE HIT ---")
            # Verify cache is empty initially
            assert await permission_cache.get_permissions(employee.id) is None
            print("Cache is empty initially (Cache Miss).")

            # Get permissions (this will read from DB and populate cache)
            role_id, db_perms = await employee_service.get_permissions_from_db(db, employee.id)
            await permission_cache.set_permissions(employee.id, role_id, db_perms)
            
            # Verify cache is now populated
            cached_perms_1 = await permission_cache.get_permissions(employee.id)
            assert cached_perms_1 == db_perms
            assert len(cached_perms_1) > 0
            print("Permissions successfully cached.")

            # Second read is a Cache Hit (no DB interaction needed)
            cached_perms_2 = await permission_cache.get_permissions(employee.id)
            assert cached_perms_2 == cached_perms_1
            print("Cache Hit confirmed. Retrieved identical cached permissions list.")

            # 3. TEST WILDCARD PERMISSION MATCHING
            print("\n--- [3] TESTING WILDCARD PERMISSIONS MATCHING ---")
            # Let's define the dependency checks
            # 3a. Viewer role has *:view permission
            dep_orders_view = RequirePermission("orders:view")
            dep_payments_view = RequirePermission("payments:view")
            dep_orders_create = RequirePermission("orders:create")

            # Mock FastAPI injection call: RequirePermission returns Employee if authorized
            # orders:view should succeed (*:view matches orders:view)
            emp_res = await dep_orders_view(db, employee, employee_service)
            assert emp_res.id == employee.id
            print("Wildcard match: 'orders:view' successfully allowed by '*:view'.")

            # payments:view should succeed (*:view matches payments:view)
            emp_res_pay = await dep_payments_view(db, employee, employee_service)
            assert emp_res_pay.id == employee.id
            print("Wildcard match: 'payments:view' successfully allowed by '*:view'.")

            # orders:create should FAIL (*:view does NOT match orders:create)
            from app.core.exceptions import ForbiddenException
            try:
                await dep_orders_create(db, employee, employee_service)
                assert False, "orders:create should have been blocked for Viewer role"
            except ForbiddenException:
                print("Wildcard match: 'orders:create' successfully blocked (correctly unauthorized).")

            # 3b. Admin role has *:* permission - check bypass
            employee.role = admin_role
            employee.role_id = admin_role.id
            db.add(employee)
            await db.commit()
            
            # Since role changes, we must invalidate cache
            await permission_cache.invalidate_employee(employee.id)

            # Check that orders:create is now ALLOWED due to admin bypass/wildcard
            emp_res_admin = await dep_orders_create(db, employee, employee_service)
            assert emp_res_admin.id == employee.id
            print("Admin bypass check: 'orders:create' successfully allowed for Administrator.")

            # 4. TEST EMPLOYEE UPDATE INVALIDATION
            print("\n--- [4] TESTING CACHE INVALIDATION ON EMPLOYEE UPDATE ---")
            # Cache the permissions
            role_id, db_perms = await employee_service.get_permissions_from_db(db, employee.id)
            await permission_cache.set_permissions(employee.id, role_id, db_perms)
            
            assert await permission_cache.get_permissions(employee.id) is not None

            # Change email (no cache invalidation needed)
            employee = await employee_service.update_employee(db, employee.id, EmployeeUpdate(
                email=f"new_email_{uuid.uuid4()}@colourlabs.com",
                version=employee.version
            ))
            assert await permission_cache.get_permissions(employee.id) is not None
            print("Email update did not clear permission cache.")

            # Change role (must invalidate cache!)
            employee = await employee_service.update_employee(db, employee.id, EmployeeUpdate(
                role_id=viewer_role.id,
                version=employee.version
            ))
            assert await permission_cache.get_permissions(employee.id) is None
            print("Role update successfully invalidated cached permissions.")

            # Deactivate employee (must invalidate cache!)
            role_id, db_perms = await employee_service.get_permissions_from_db(db, employee.id)
            await permission_cache.set_permissions(employee.id, role_id, db_perms)
            
            employee = await employee_service.update_employee(db, employee.id, EmployeeUpdate(
                is_active=False,
                version=employee.version
            ))
            assert await permission_cache.get_permissions(employee.id) is None
            print("Deactivation successfully invalidated cached permissions.")

        finally:
            await db.rollback()
            print("Test session transaction rolled back.")

    # 5. TEST CONCURRENT EMPLOYEE CREATION
    print("\n--- [5] TESTING CONCURRENT EMPLOYEE CREATION & SEQUENCE-SAFETY ---")
    
    # We define a function that runs in parallel with separate DB connections
    async def create_employee_task(i: int) -> str:
        async with AsyncSessionLocal() as session:
            try:
                uniq = str(uuid.uuid4())[:8]
                import random
                phone = "".join(random.choices("0123456789", k=10))
                schema = EmployeeCreate(
                    first_name=f"Concurrent{i}",
                    last_name="Staff",
                    email=f"concurrent_staff_{i}_{uniq}@colourlabs.com",
                    phone=phone,
                    password="SecurePassword123!",
                    role_id=None
                )

                emp = await employee_service.create_employee(session, schema)
                code = emp.employee_code
                return code
            except Exception as e:
                await session.rollback()
                raise e

    # Spin up 10 concurrent creation requests
    print("Launching 10 concurrent employee creations in parallel...")
    tasks = [create_employee_task(i) for i in range(10)]
    employee_codes = await asyncio.gather(*tasks)

    print(f"Generated Employee Codes: {employee_codes}")
    # Verify all generated codes are unique
    assert len(employee_codes) == 10
    assert len(set(employee_codes)) == 10, "Duplicate employee codes generated!"
    print("Concurrency safety verified successfully! Zero code collisions occurred.")

    # Let's clean up the created employees
    async with AsyncSessionLocal() as session:
        for code in employee_codes:
            stmt = select(Employee).where(Employee.employee_code == code)
            res = await session.execute(stmt)
            emp = res.scalars().first()
            if emp:
                await session.delete(emp)
        await session.commit()
    print("Cleaned up concurrent test employees successfully.")

    print("\n=== ALL PERMISSION CACHE & CONCURRENCY TESTS COMPLETED SUCCESSFULLY ===")


if __name__ == "__main__":
    asyncio.run(test_permissions_suite())

