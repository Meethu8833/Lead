"""
scripts/seed_roles.py

Idempotent seed script to initialize security roles, permissions,
and their associations in the database.
Can be executed manually:
    python scripts/seed_roles.py
"""

import asyncio
import sys
import os

# Add the project root to sys.path so we can import app modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.core.database import AsyncSessionLocal
from app.models.role import Role
from app.models.permission import Permission

# ==========================
# DEFINITION OF PERMISSIONS
# ==========================
PERMISSIONS = [
    # orders
    ("orders", "create"),
    ("orders", "update"),
    ("orders", "delete"),
    ("orders", "view"),
    ("orders", "*"),
    # payments
    ("payments", "create"),
    ("payments", "update"),
    ("payments", "delete"),
    ("payments", "view"),
    ("payments", "*"),
    # inventory
    ("inventory", "create"),
    ("inventory", "update"),
    ("inventory", "delete"),
    ("inventory", "view"),
    ("inventory", "*"),
    # dashboard
    ("dashboard", "view"),
    # production
    ("production", "update"),
    ("production", "view"),
    ("production", "*"),
    # invoices
    ("invoices", "create"),
    ("invoices", "update"),
    ("invoices", "delete"),
    ("invoices", "view"),
    ("invoices", "*"),
    # delivery
    ("delivery", "create"),
    ("delivery", "update"),
    ("delivery", "delete"),
    ("delivery", "view"),
    ("delivery", "*"),
    # reports
    ("reports", "view"),
    # employees
    ("employees", "create"),
    ("employees", "update"),
    ("employees", "delete"),
    ("employees", "view"),
    ("employees", "*"),
    # photographers
    ("photographers", "create"),
    ("photographers", "update"),
    ("photographers", "delete"),
    ("photographers", "view"),
    ("photographers", "*"),
    # wildcards
    ("*", "*"),
    ("*", "view"),
]

# ==========================
# DEFINITION OF ROLES
# ==========================
ROLE_PERMISSIONS_MAPPING = {
    "Administrator": {
        "description": "System administrator with full database bypass",
        "is_system": True,
        "patterns": [("*", "*")]
    },
    "Manager": {
        "description": "Operational manager overseeing all CRM modules",
        "is_system": False,
        "patterns": [
            ("orders", "*"), ("payments", "*"), ("inventory", "*"),
            ("dashboard", "view"), ("production", "*"), ("invoices", "*"),
            ("delivery", "*"), ("reports", "view"), ("employees", "*"),
            ("photographers", "*")
        ]
    },
    "Reception": {
        "description": "Front-desk receptionist managing bookings and payments",
        "is_system": False,
        "patterns": [
            ("orders", "create"), ("orders", "view"), ("orders", "update"),
            ("payments", "create"), ("payments", "view"), ("photographers", "*"),
            ("dashboard", "view")
        ]
    },
    "Designer": {
        "description": "Album design specialist",
        "is_system": False,
        "patterns": [
            ("orders", "view"), ("production", "view"), ("production", "update"),
            ("dashboard", "view")
        ]
    },
    "Editor": {
        "description": "Photo correction and retouching editor",
        "is_system": False,
        "patterns": [
            ("orders", "view"), ("production", "view"), ("production", "update"),
            ("dashboard", "view")
        ]
    },
    "Color Correction": {
        "description": "Color profiling and balance correction specialist",
        "is_system": False,
        "patterns": [
            ("orders", "view"), ("production", "view"), ("production", "update")
        ]
    },
    "Printing": {
        "description": "Lab printing operator",
        "is_system": False,
        "patterns": [
            ("orders", "view"), ("production", "view"), ("production", "update"),
            ("inventory", "view")
        ]
    },
    "Lamination": {
        "description": "Lamination operator",
        "is_system": False,
        "patterns": [
            ("orders", "view"), ("production", "view"), ("production", "update")
        ]
    },
    "Quality Check": {
        "description": "Product quality assurance specialist",
        "is_system": False,
        "patterns": [
            ("orders", "view"), ("production", "view"), ("production", "update")
        ]
    },
    "Packing": {
        "description": "Finished product packaging operator",
        "is_system": False,
        "patterns": [
            ("orders", "view"), ("production", "view"), ("production", "update")
        ]
    },
    "Delivery": {
        "description": "Courier and dispatch clerk",
        "is_system": False,
        "patterns": [
            ("orders", "view"), ("delivery", "*")
        ]
    },
    "Accountant": {
        "description": "Financial ledger and invoicing specialist",
        "is_system": False,
        "patterns": [
            ("invoices", "*"), ("payments", "*"), ("reports", "view"),
            ("dashboard", "view")
        ]
    },
    "Viewer": {
        "description": "Read-only access across all operations",
        "is_system": False,
        "patterns": [("*", "view")]
    }
}


async def seed_data():
    """
    Main seed process connecting to the database and setting up seed rows.
    """
    print("Starting database seeding...")
    async with AsyncSessionLocal() as session:
        try:
            # 1. Seed Permissions
            db_permissions_map = {}
            for module, action in PERMISSIONS:
                # Check if exists
                stmt = select(Permission).where(Permission.module == module, Permission.action == action)
                res = await session.execute(stmt)
                perm = res.scalars().first()
                if not perm:
                    perm = Permission(module=module, action=action)
                    session.add(perm)
                    await session.flush()  # Populates id
                    print(f"Created permission: {module}:{action}")
                db_permissions_map[(module, action)] = perm

            # 2. Seed Roles and Associate Permissions
            for role_name, config in ROLE_PERMISSIONS_MAPPING.items():
                stmt = select(Role).options(selectinload(Role.permissions)).where(Role.name == role_name)
                res = await session.execute(stmt)
                role = res.scalars().first()

                if not role:
                    role = Role(
                        name=role_name,
                        description=config["description"],
                        is_system=config["is_system"]
                    )
                    session.add(role)
                    await session.flush()
                    print(f"Created role: {role_name}")

                # Resolve permissions targets
                target_perms = []
                for p_mod, p_act in config["patterns"]:
                    perm = db_permissions_map.get((p_mod, p_act))
                    if perm:
                        target_perms.append(perm)

                # Set relations idempotently
                role.permissions = target_perms
                session.add(role)
                print(f"Mapped {len(target_perms)} permissions to role: {role_name}")

            await session.commit()
            print("Database seeding completed successfully!")
        except Exception as e:
            await session.rollback()
            print(f"Error during seeding: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(seed_data())
