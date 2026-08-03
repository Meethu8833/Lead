"""
app/services/employee.py

Defines the EmployeeService implementation.
Under Clean Architecture, this resides in the Application Business Rules (Use Cases) layer.
"""

import uuid
import secrets
from datetime import datetime, timedelta, timezone
from typing import Sequence
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.core.exceptions import BadRequestException, NotFoundException, ConflictException
from app.models.employee import Employee
from app.models.role import Role
from app.models.permission import Permission
from app.models.audit_log import AuditLog, AuditAction
from app.schemas.employee import EmployeeCreate, EmployeeUpdate
from app.repositories.employee import EmployeeRepository
from app.repositories.role import RoleRepository
from app.services.auth import hash_password, verify_password
from app.services.cache import permission_cache


class EmployeeService:
    """
    EmployeeService handles profile configuration, password resets,
    and coordinates with the PermissionCache during updates.
    """

    def __init__(
        self,
        employee_repo: EmployeeRepository | None = None,
        role_repo: RoleRepository | None = None,
    ) -> None:
        self.employee_repo = employee_repo or EmployeeRepository()
        self.role_repo = role_repo or RoleRepository()

    async def create_employee(self, db: AsyncSession, schema: EmployeeCreate) -> Employee:
        """
        Registers a new Employee.
        Generates employee_code using the PostgreSQL sequence.
        Verifies phone and email uniqueness.
        """
        # Uniqueness checks
        existing_email = await self.employee_repo.get_by_email(db, schema.email)
        if existing_email:
            raise BadRequestException(f"Employee with email '{schema.email}' already exists.")

        existing_phone = await self.employee_repo.get_by_phone(db, schema.phone)
        if existing_phone:
            raise BadRequestException(f"Employee with phone '{schema.phone}' already exists.")

        if schema.role_id:
            role = await self.role_repo.get_role_by_id(db, schema.role_id)
            if not role:
                raise NotFoundException(f"Role with ID '{schema.role_id}' was not found.")

        # Concurrency-safe, sequence-backed code generation
        employee_code = await self.employee_repo.get_next_employee_code(db)

        # Create employee record
        hashed = hash_password(schema.password)
        employee = Employee(
            employee_code=employee_code,
            first_name=schema.first_name,
            last_name=schema.last_name,
            email=schema.email,
            phone=schema.phone,
            password_hash=hashed,
            department=schema.department,
            designation=schema.designation,
            role_id=schema.role_id,
            is_active=True,
        )

        return await self.employee_repo.create(db, employee)

    async def get_employee_by_id(self, db: AsyncSession, id: uuid.UUID) -> Employee:
        """
        Fetches an employee by ID. Raises NotFoundException if not found.
        """
        employee = await self.employee_repo.get_by_id(db, id)
        if not employee:
            raise NotFoundException(f"Employee with ID '{id}' was not found.")
        return employee

    async def get_all_employees(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> Sequence[Employee]:
        """
        Fetches a list of all employees.
        """
        return await self.employee_repo.get_all(db, skip=skip, limit=limit)

    async def update_employee(self, db: AsyncSession, id: uuid.UUID, schema: EmployeeUpdate) -> Employee:
        """
        Updates an employee profile.
        Triggers PermissionCache invalidation if role or active status changes.
        """
        employee = await self.employee_repo.get_by_id(db, id)
        if not employee:
            raise NotFoundException(f"Employee with ID '{id}' was not found.")

        # Optimistic Locking Version Check
        if schema.version is not None and employee.version != schema.version:
            raise ConflictException("Employee was modified by another process. Please reload.")

        update_data = schema.model_dump(exclude_unset=True)
        update_data.pop("version", None)

        # Confict validation
        new_email = update_data.get("email")
        if new_email and new_email != employee.email:
            existing = await self.employee_repo.get_by_email(db, new_email)
            if existing:
                raise BadRequestException(f"Employee with email '{new_email}' already exists.")

        new_phone = update_data.get("phone")
        if new_phone and new_phone != employee.phone:
            existing = await self.employee_repo.get_by_phone(db, new_phone)
            if existing:
                raise BadRequestException(f"Employee with phone '{new_phone}' already exists.")

        role_changed = False
        new_role_id = update_data.get("role_id")
        if "role_id" in update_data and new_role_id != employee.role_id:
            role_changed = True
            if new_role_id:
                role = await self.role_repo.get_role_by_id(db, new_role_id)
                if not role:
                    raise NotFoundException(f"Role with ID '{new_role_id}' was not found.")

        deactivated = False
        new_active = update_data.get("is_active")
        if new_active is not None and new_active != employee.is_active:
            if not new_active:
                deactivated = True

        updated_employee = await self.employee_repo.update(db, employee, update_data)

        # Invalidate Cache automatically when role changes or employee is deactivated
        if role_changed or deactivated:
            await permission_cache.invalidate_employee(id)
            if deactivated:
                # Force logout by deleting all refresh tokens
                await self.employee_repo.delete_all_sessions_for_employee(db, id)

        return updated_employee

    async def delete_employee(self, db: AsyncSession, id: uuid.UUID) -> None:
        """
        Deletes an employee from database. Invalidate cache.
        """
        employee = await self.employee_repo.get_by_id(db, id)
        if not employee:
            raise NotFoundException(f"Employee with ID '{id}' was not found.")

        await self.employee_repo.delete(db, employee)
        await permission_cache.invalidate_employee(id)
        await self.employee_repo.delete_all_sessions_for_employee(db, id)

    # ==========================
    # PASSWORD MANAGEMENT
    # ==========================

    async def change_password(self, db: AsyncSession, id: uuid.UUID, old_pw: str, new_pw: str) -> None:
        """
        Validates old password and updates it to new one.
        """
        employee = await self.employee_repo.get_by_id(db, id)
        if not employee:
            raise NotFoundException(f"Employee not found.")

        if not verify_password(old_pw, employee.password_hash):
            raise BadRequestException("Invalid old password.", error_code="INVALID_OLD_PASSWORD")

        hashed = hash_password(new_pw)
        await self.employee_repo.update(db, employee, {"password_hash": hashed})

        # Invalidate all active sessions for security except the current one (or all).
        # We delete all sessions to enforce re-authentication.
        await self.employee_repo.delete_all_sessions_for_employee(db, id)

        # Log password reset/change audit event
        audit = AuditLog(
            entity_name="Employee",
            entity_id=id,
            action=AuditAction.PASSWORD_RESET,
            performed_by=employee.email,
            old_values=None,
            new_values={"event": "password_changed"},
        )
        db.add(audit)
        await db.commit()

    async def forgot_password(self, db: AsyncSession, email: str) -> str:
        """
        Generates password reset token expiring in 15 minutes.
        Returns the token for simulation/testing.
        """
        employee = await self.employee_repo.get_by_email(db, email)
        if not employee:
            # Silence warning to prevent user enumeration security disclosure,
            # but we return a generic message in controllers. We still raise if tested directly.
            raise NotFoundException(f"Employee with email '{email}' was not found.")

        token = secrets.token_urlsafe(32)
        expiry = datetime.now(timezone.utc) + timedelta(minutes=15)

        await self.employee_repo.update(
            db,
            employee,
            {"reset_token": token, "reset_token_expires_at": expiry}
        )

        logger.info(f"Password reset token generated for {email}: {token}")
        return token

    async def reset_password(self, db: AsyncSession, token: str, new_password: str) -> None:
        """
        Validates token and updates password. Revokes all active sessions.
        """
        # Look up employee by reset token
        now = datetime.now(timezone.utc)
        query = select(Employee).where(
            Employee.reset_token == token,
            Employee.reset_token_expires_at > now
        )
        result = await db.execute(query)
        employee = result.scalars().first()

        if not employee:
            raise BadRequestException("Invalid or expired reset token.", error_code="INVALID_RESET_TOKEN")

        # Update password
        hashed = hash_password(new_password)
        await self.employee_repo.update(
            db,
            employee,
            {
                "password_hash": hashed,
                "reset_token": None,
                "reset_token_expires_at": None
            }
        )

        # Invalidate all active sessions
        await self.employee_repo.delete_all_sessions_for_employee(db, employee.id)
        await permission_cache.invalidate_employee(employee.id)

        # Audit
        audit = AuditLog(
            entity_name="Employee",
            entity_id=employee.id,
            action=AuditAction.PASSWORD_RESET,
            performed_by=employee.email,
            old_values=None,
            new_values={"event": "password_reset_via_token"},
        )
        db.add(audit)
        await db.commit()

    # ==========================
    # PROFILE MANAGEMENT
    # ==========================

    async def update_phone(self, db: AsyncSession, id: uuid.UUID, phone: str) -> Employee:
        """
        Updates phone number.
        """
        return await self.update_employee(db, id, EmployeeUpdate(phone=phone))

    async def update_email(self, db: AsyncSession, id: uuid.UUID, email: str) -> Employee:
        """
        Updates email address.
        """
        return await self.update_employee(db, id, EmployeeUpdate(email=email))

    async def update_profile_photo(self, db: AsyncSession, id: uuid.UUID, photo_url: str) -> Employee:
        """
        Updates profile photo URL.
        """
        employee = await self.employee_repo.get_by_id(db, id)
        if not employee:
            raise NotFoundException(f"Employee not found.")
        return await self.employee_repo.update(db, employee, {"profile_photo_url": photo_url})

    # ==========================
    # PERMISSION LOOKUP & CACHING
    # ==========================

    async def get_permissions_from_db(self, db: AsyncSession, employee_id: uuid.UUID) -> tuple[uuid.UUID | None, list[str]]:
        """
        Loads permissions for an employee from the database.
        """
        query = (
            select(Employee)
            .options(
                selectinload(Employee.role).selectinload(Role.permissions)
            )
            .where(Employee.id == employee_id)
        )
        result = await db.execute(query)
        employee = result.scalars().first()

        if not employee or not employee.is_active:
            return None, []

        role = employee.role
        if not role:
            return None, []

        # Convert permissions list to flat list of strings
        permissions_list = [f"{p.module}:{p.action}" for p in role.permissions]
        return role.id, permissions_list

    async def warm_cache(self, db: AsyncSession) -> None:
        """
        Fetches all active employees, resolves their permissions, and warms the PermissionCache.
        """
        query = select(Employee).options(selectinload(Employee.role).selectinload(Role.permissions)).where(Employee.is_active == True)
        result = await db.execute(query)
        employees = result.scalars().all()

        mapping = {}
        for emp in employees:
            role = emp.role
            role_id = role.id if role else None
            perms = [f"{p.module}:{p.action}" for p in role.permissions] if role else []
            mapping[emp.id] = (role_id, perms)

        await permission_cache.warm_cache(mapping)
