"""
tests/test_roles.py

Integration tests for the Roles and Permissions Seeding module.
Verifies:
1. Seed Script idempotency (running multiple times never duplicates database records).
2. Role CRUD operations.
3. Cache invalidation triggers when a Role's permissions change.
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
from app.models.role import Role
from app.models.permission import Permission
from app.schemas.role import RoleCreate, RoleUpdate
from app.repositories.role import RoleRepository
from app.services.cache import permission_cache
from scripts.seed_roles import seed_data


async def test_roles_suite():
    print("=== STARTING ROLES & SEEDING INTEGRATION TESTS ===")

    role_repo = RoleRepository()

    async with AsyncSessionLocal() as db:
        try:
            # 1. TEST SEED SCRIPT IDEMPOTENCY
            print("\n--- [1] TESTING SEED SCRIPT IDEMPOTENCY ---")
            
            # Count roles and permissions before seeding
            stmt_roles = select(Role)
            res_roles = await db.execute(stmt_roles)
            roles_count_1 = len(res_roles.scalars().all())
            
            stmt_perms = select(Permission)
            res_perms = await db.execute(stmt_perms)
            perms_count_1 = len(res_perms.scalars().all())
            
            print(f"Initial DB state: {roles_count_1} roles, {perms_count_1} permissions.")

            # Run seeding script function
            await seed_data()

            # Count again
            res_roles = await db.execute(stmt_roles)
            roles_count_2 = len(res_roles.scalars().all())
            
            res_perms = await db.execute(stmt_perms)
            perms_count_2 = len(res_perms.scalars().all())
            
            print(f"After seed 1: {roles_count_2} roles, {perms_count_2} permissions.")
            assert roles_count_2 >= 13  # Default roles are present
            assert perms_count_2 >= 40  # Default permissions are present

            # Run seeding script function again (idempotency check)
            await seed_data()

            res_roles = await db.execute(stmt_roles)
            roles_count_3 = len(res_roles.scalars().all())
            
            res_perms = await db.execute(stmt_perms)
            perms_count_3 = len(res_perms.scalars().all())
            
            print(f"After seed 2 (re-run): {roles_count_3} roles, {perms_count_3} permissions.")
            assert roles_count_3 == roles_count_2
            assert perms_count_3 == perms_count_2
            print("Idempotency successfully verified! Re-running did not duplicate records.")

            # 2. ROLE CRUD OPERATIONS
            print("\n--- [2] TESTING ROLE CRUD ---")
            # Fetch some permissions from DB
            res_perms = await db.execute(select(Permission).limit(5))
            db_permissions = res_perms.scalars().all()
            assert len(db_permissions) >= 2

            # Create
            unique_role_name = f"Test Designer {uuid.uuid4()}"
            role = Role(
                name=unique_role_name,
                description="Test description",
                is_system=False
            )
            role.permissions = [db_permissions[0], db_permissions[1]]
            created_role = await role_repo.create_role(db, role)
            assert created_role.id is not None
            assert created_role.name == unique_role_name
            print(f"Role '{created_role.name}' created.")

            # Read
            fetched_role = await role_repo.get_role_by_id(db, created_role.id)
            assert fetched_role is not None
            assert fetched_role.name == unique_role_name
            assert len(fetched_role.permissions) == 2
            print("Role successfully read from DB with 2 permissions.")

            # Update
            new_desc = "Updated description"
            update_data = {
                "description": new_desc,
                "permissions": [db_permissions[0], db_permissions[1], db_permissions[2]]
            }
            updated_role = await role_repo.update_role(db, fetched_role, update_data)
            assert updated_role.description == new_desc
            
            # Fetch again to eagerly load updated permissions relation
            refetched_role = await role_repo.get_role_by_id(db, updated_role.id)
            assert len(refetched_role.permissions) == 3
            print("Role successfully updated with new description and permissions.")

            # Delete
            await role_repo.delete_role(db, refetched_role)
            deleted_check = await role_repo.get_role_by_id(db, created_role.id)
            assert deleted_check is None
            print("Role successfully deleted.")


            # 3. CACHE INVALIDATION ON ROLE CHANGE
            print("\n--- [3] TESTING CACHE INVALIDATION ON ROLE UPDATE ---")
            # Warm cache with mock employee
            emp_id = uuid.uuid4()
            role_id = uuid.uuid4()
            perms = ["orders:view", "orders:create"]
            
            await permission_cache.set_permissions(emp_id, role_id, perms)
            
            # Check cache contains values
            cached = await permission_cache.get_permissions(emp_id)
            assert cached == perms
            print("Cached mock permissions successfully mapped.")

            # Invalidate role
            await permission_cache.invalidate_role(role_id)

            # Check cache is now cleared
            cached_after = await permission_cache.get_permissions(emp_id)
            assert cached_after is None
            print("Invalidate role successfully cleared associated employee permission caches.")

            print("\n=== ALL ROLES & SEEDING INTEGRATION TESTS COMPLETED SUCCESSFULLY ===")

        finally:
            # Rollback to keep database clean
            await db.rollback()
            print("Database transaction rolled back successfully.")


if __name__ == "__main__":
    asyncio.run(test_roles_suite())
