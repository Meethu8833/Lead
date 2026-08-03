"""
scripts/create_admin.py

Creates the first admin Employee so there is a login for the CRM.
Assigns the "Administrator" role (run scripts/seed_roles.py first so it exists).
Can be executed manually:
    python scripts/create_admin.py
"""

import asyncio
import sys
import os

# Add the project root to sys.path so we can import app modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.role import Role
from app.schemas.employee import EmployeeCreate
from app.services.employee import EmployeeService

# ==========================
# ADMIN ACCOUNT DETAILS
# ==========================
ADMIN_EMAIL = "admin@colourlabs.com"
ADMIN_PASSWORD = "Admin@123"
ADMIN_FIRST_NAME = "Admin"
ADMIN_LAST_NAME = "User"
ADMIN_PHONE = "+911234567890"


async def create_admin():
    print("Creating first admin employee...")
    async with AsyncSessionLocal() as session:
        try:
            stmt = select(Role).where(Role.name == "Administrator")
            res = await session.execute(stmt)
            admin_role = res.scalars().first()

            if not admin_role:
                print("Administrator role not found. Run 'python scripts/seed_roles.py' first.")
                return

            service = EmployeeService()
            schema = EmployeeCreate(
                first_name=ADMIN_FIRST_NAME,
                last_name=ADMIN_LAST_NAME,
                email=ADMIN_EMAIL,
                phone=ADMIN_PHONE,
                password=ADMIN_PASSWORD,
                role_id=admin_role.id,
            )
            employee = await service.create_employee(session, schema)
            await session.commit()
            print(f"Admin employee created: {employee.email} (code: {employee.employee_code})")
            print(f"Login with email='{ADMIN_EMAIL}' password='{ADMIN_PASSWORD}'")
        except Exception as e:
            await session.rollback()
            print(f"Error creating admin: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(create_admin())
