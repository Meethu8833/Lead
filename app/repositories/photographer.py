"""
app/repositories/photographer.py

This file implements the PhotographerRepository.
Under Clean Architecture, this file belongs to the Interface Adapters layer.
It encapsulates SQL database access (via SQLAlchemy 2.0) and translates database rows
into rich objects (or models) that can be consumed by the business logic (Services).
By isolating SQL statements here, we keep services free of data access technologies.
"""

import uuid
from typing import Sequence
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.photographer import Photographer, LeadStatus


class PhotographerRepository:
    """
    Photographer Repository.
    Handles CRUD operations on the photographers database table using SQLAlchemy.
    """

    def __init__(self, include_deleted: bool = False) -> None:
        self.include_deleted = include_deleted

    async def create(self, db: AsyncSession, photographer: Photographer) -> Photographer:
        """
        Persists a new Photographer record to the database.
        """
        db.add(photographer)
        await db.commit()
        await db.refresh(photographer)
        return photographer

    async def get_by_id(self, db: AsyncSession, id: uuid.UUID, include_deleted: bool | None = None) -> Photographer | None:
        """
        Fetches a single Photographer by their UUID.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        if inc:
            return await db.get(Photographer, id)
        
        query = select(Photographer).where(Photographer.id == id, Photographer.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().first()

    async def get_by_phone(self, db: AsyncSession, phone: str, include_deleted: bool | None = None) -> Photographer | None:
        """
        Fetches a Photographer by their phone number (unique constraint).
        Used for validation during registration.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(Photographer).where(Photographer.phone == phone)
        if not inc:
            query = query.where(Photographer.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().first()

    async def get_all(self, db: AsyncSession, skip: int = 0, limit: int = 100, include_deleted: bool | None = None) -> Sequence[Photographer]:
        """
        Fetches a list of all photographers with pagination.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(Photographer).offset(skip).limit(limit)
        if not inc:
            query = query.where(Photographer.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().all()

    async def update(self, db: AsyncSession, db_obj: Photographer, update_data: dict) -> Photographer:
        """
        Updates a photographer's attributes and commits changes.
        """
        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)
        
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def delete(self, db: AsyncSession, db_obj: Photographer) -> bool:
        """
        Soft deletes a photographer record from the database.
        """
        db_obj.is_deleted = True
        db_obj.deleted_at = datetime.now(timezone.utc)
        db.add(db_obj)
        await db.commit()
        return True

    async def get_by_status(
        self, db: AsyncSession, status: LeadStatus, skip: int = 0, limit: int = 100, include_deleted: bool | None = None
    ) -> Sequence[Photographer]:
        """
        Fetches photographers filtering by lead status.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(Photographer).where(Photographer.lead_status == status).offset(skip).limit(limit)
        if not inc:
            query = query.where(Photographer.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().all()

    async def get_followups_due(
        self, db: AsyncSession, skip: int = 0, limit: int = 100, include_deleted: bool | None = None
    ) -> Sequence[Photographer]:
        """
        Fetches photographers whose next followup is in the past.
        """
        from sqlalchemy import func
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = (
            select(Photographer)
            .where(Photographer.next_followup_at.isnot(None))
            .where(Photographer.next_followup_at < func.now())
            .offset(skip)
            .limit(limit)
        )
        if not inc:
            query = query.where(Photographer.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().all()

    async def search(
        self,
        db: AsyncSession,
        name: str | None = None,
        phone: str | None = None,
        city: str | None = None,
        studio_name: str | None = None,
        skip: int = 0,
        limit: int = 100,
        include_deleted: bool | None = None,
    ) -> Sequence[Photographer]:
        """
        Searches photographers using case-insensitive partial match on name, phone, city, or studio_name.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(Photographer)
        filters = []
        if name:
            filters.append(Photographer.name.ilike(f"%{name}%"))
        if phone:
            filters.append(Photographer.phone.ilike(f"%{phone}%"))
        if city:
            filters.append(Photographer.city.ilike(f"%{city}%"))
        if studio_name:
            filters.append(Photographer.studio_name.ilike(f"%{studio_name}%"))
        if not inc:
            filters.append(Photographer.is_deleted == False)
            
        if filters:
            query = query.where(*filters)
            
        query = query.offset(skip).limit(limit)
        result = await db.execute(query)
        return result.scalars().all()


class AdminPhotographerRepository(PhotographerRepository):
    """
    Photographer Repository that includes soft-deleted items by default.
    """
    def __init__(self) -> None:
        super().__init__(include_deleted=True)


