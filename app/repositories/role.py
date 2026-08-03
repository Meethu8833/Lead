"""
app/repositories/role.py

This file implements the RoleRepository.
Under Clean Architecture, this resides in the Interface Adapters layer.
"""

import uuid
from typing import Sequence
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.role import Role
from app.models.permission import Permission


class RoleRepository:
    """
    Role Repository.
    Handles data operations on the roles, permissions, and role_permissions tables.
    """

    # ==========================
    # ROLE CRUD
    # ==========================

    async def create_role(self, db: AsyncSession, role: Role) -> Role:
        """
        Persists a new Role record.
        """
        db.add(role)
        await db.commit()
        await db.refresh(role)
        return role

    async def get_role_by_id(self, db: AsyncSession, id: uuid.UUID) -> Role | None:
        """
        Fetches a Role by UUID, pre-loading permissions.
        """
        query = select(Role).options(selectinload(Role.permissions)).where(Role.id == id)
        result = await db.execute(query)
        return result.scalars().first()

    async def get_role_by_name(self, db: AsyncSession, name: str) -> Role | None:
        """
        Fetches a Role by name, pre-loading permissions.
        """
        query = select(Role).options(selectinload(Role.permissions)).where(Role.name == name)
        result = await db.execute(query)
        return result.scalars().first()

    async def get_all_roles(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> Sequence[Role]:
        """
        Fetches a paginated list of all Roles, pre-loading permissions.
        """
        query = select(Role).options(selectinload(Role.permissions)).offset(skip).limit(limit)
        result = await db.execute(query)
        return result.scalars().all()

    async def update_role(self, db: AsyncSession, db_obj: Role, update_data: dict) -> Role:
        """
        Updates a Role's attributes.
        """
        # Handle relationship updates if permissions are provided
        permissions = update_data.pop("permissions", None)
        if permissions is not None:
            db_obj.permissions = permissions

        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)

        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def delete_role(self, db: AsyncSession, db_obj: Role) -> bool:
        """
        Deletes a Role record.
        """
        await db.delete(db_obj)
        await db.commit()
        return True

    # ==========================
    # PERMISSION CRUD
    # ==========================

    async def create_permission(self, db: AsyncSession, permission: Permission) -> Permission:
        """
        Persists a new Permission.
        """
        db.add(permission)
        await db.commit()
        await db.refresh(permission)
        return permission

    async def get_permission_by_id(self, db: AsyncSession, id: uuid.UUID) -> Permission | None:
        """
        Fetches a Permission by UUID.
        """
        query = select(Permission).where(Permission.id == id)
        result = await db.execute(query)
        return result.scalars().first()

    async def get_permission_by_module_action(self, db: AsyncSession, module: str, action: str) -> Permission | None:
        """
        Fetches a Permission by module and action.
        """
        query = select(Permission).where(Permission.module == module, Permission.action == action)
        result = await db.execute(query)
        return result.scalars().first()

    async def get_all_permissions(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> Sequence[Permission]:
        """
        Fetches a paginated list of all Permissions.
        """
        query = select(Permission).offset(skip).limit(limit)
        result = await db.execute(query)
        return result.scalars().all()

    async def get_permissions_by_ids(self, db: AsyncSession, ids: list[uuid.UUID]) -> Sequence[Permission]:
        """
        Fetches a list of Permissions matching a list of UUIDs.
        """
        if not ids:
            return []
        query = select(Permission).where(Permission.id.in_(ids))
        result = await db.execute(query)
        return result.scalars().all()
