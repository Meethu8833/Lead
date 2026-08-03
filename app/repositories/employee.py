"""
app/repositories/employee.py

This file implements the EmployeeRepository.
Under Clean Architecture, this resides in the Interface Adapters layer.
"""

import uuid
from typing import Sequence
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.employee import Employee
from app.models.session import UserSession


class EmployeeRepository:
    """
    Employee Repository.
    Handles data operations on the employees and user_sessions tables using SQLAlchemy.
    """

    async def get_next_employee_code(self, db: AsyncSession) -> str:
        """
        Fetches the next value from the PostgreSQL sequence 'employee_code_seq'
        to generate a concurrency-safe, unique employee code.
        """
        result = await db.execute(text("SELECT nextval('employee_code_seq')"))
        next_val = result.scalar()
        return f"EMP-{next_val:06d}"

    async def create(self, db: AsyncSession, employee: Employee) -> Employee:
        """
        Persists a new Employee record to the database.
        """
        db.add(employee)
        await db.commit()
        await db.refresh(employee)
        return employee

    async def get_by_id(self, db: AsyncSession, id: uuid.UUID) -> Employee | None:
        """
        Fetches a single Employee by UUID, loading their role.
        """
        query = select(Employee).where(Employee.id == id)
        result = await db.execute(query)
        return result.scalars().first()

    async def get_by_email(self, db: AsyncSession, email: str) -> Employee | None:
        """
        Fetches an Employee by their unique email.
        """
        query = select(Employee).where(Employee.email == email)
        result = await db.execute(query)
        return result.scalars().first()

    async def get_by_phone(self, db: AsyncSession, phone: str) -> Employee | None:
        """
        Fetches an Employee by their unique phone number.
        """
        query = select(Employee).where(Employee.phone == phone)
        result = await db.execute(query)
        return result.scalars().first()

    async def get_all(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> Sequence[Employee]:
        """
        Fetches a paginated list of all employees.
        """
        query = select(Employee).offset(skip).limit(limit)
        result = await db.execute(query)
        return result.scalars().all()

    async def update(self, db: AsyncSession, db_obj: Employee, update_data: dict) -> Employee:
        """
        Updates an employee's attributes and commits changes.
        """
        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def delete(self, db: AsyncSession, db_obj: Employee) -> bool:
        """
        Deletes an employee record from the database.
        """
        await db.delete(db_obj)
        await db.commit()
        return True

    # ==========================
    # USER SESSION OPERATIONS
    # ==========================

    async def create_session(self, db: AsyncSession, session: UserSession) -> UserSession:
        """
        Persists a new UserSession record to the database.
        """
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session

    async def get_session_by_hash(self, db: AsyncSession, token_hash: str) -> UserSession | None:
        """
        Fetches a UserSession by its unique token hash.
        """
        query = select(UserSession).where(UserSession.token_hash == token_hash)
        result = await db.execute(query)
        return result.scalars().first()

    async def get_active_sessions_for_employee(self, db: AsyncSession, employee_id: uuid.UUID) -> Sequence[UserSession]:
        """
        Fetches all active (non-revoked, non-expired) sessions for an employee.
        """
        query = (
            select(UserSession)
            .where(
                UserSession.employee_id == employee_id,
                UserSession.is_revoked == False,
                UserSession.expires_at > func.now()
            )
        )
        result = await db.execute(query)
        return result.scalars().all()

    async def update_session(self, db: AsyncSession, session: UserSession) -> UserSession:
        """
        Saves changes to a UserSession.
        """
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session

    async def delete_session(self, db: AsyncSession, session: UserSession) -> None:
        """
        Deletes a specific UserSession.
        """
        await db.delete(session)
        await db.commit()

    async def delete_all_sessions_for_employee(self, db: AsyncSession, employee_id: uuid.UUID) -> int:
        """
        Deletes or invalidates all sessions for a specific employee.
        """
        from sqlalchemy import delete
        stmt = delete(UserSession).where(UserSession.employee_id == employee_id)
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount

    async def delete_expired_sessions(self, db: AsyncSession) -> int:
        """
        Deletes all expired or explicitly revoked sessions from the database.
        """
        from sqlalchemy import delete, or_
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        stmt = delete(UserSession).where(
            or_(
                UserSession.expires_at < now,
                UserSession.is_revoked == True
            )
        )
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount
