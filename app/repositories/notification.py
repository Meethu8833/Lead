"""
app/repositories/notification.py

Repository for NotificationLog database operations.
"""

import uuid
from typing import Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.notification import NotificationLog, NotificationStatus


class NotificationRepository:
    async def create(self, db: AsyncSession, notification: NotificationLog, commit: bool = True) -> NotificationLog:
        db.add(notification)
        if commit:
            await db.commit()
            await db.refresh(notification)
        return notification

    async def update(self, db: AsyncSession, db_obj: NotificationLog, update_data: dict, commit: bool = True) -> NotificationLog:
        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)
        db.add(db_obj)
        if commit:
            await db.commit()
            await db.refresh(db_obj)
        return db_obj

    async def delete(self, db: AsyncSession, db_obj: NotificationLog, commit: bool = True) -> bool:
        await db.delete(db_obj)
        if commit:
            await db.commit()
        return True

    async def get_by_id(self, db: AsyncSession, id: uuid.UUID) -> NotificationLog | None:
        return await db.get(NotificationLog, id)

    async def get_all(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> Sequence[NotificationLog]:
        query = select(NotificationLog).offset(skip).limit(limit)
        result = await db.execute(query)
        return result.scalars().all()

    async def get_by_order_id(self, db: AsyncSession, order_id: uuid.UUID) -> Sequence[NotificationLog]:
        query = select(NotificationLog).where(NotificationLog.order_id == order_id)
        result = await db.execute(query)
        return result.scalars().all()

    async def get_by_status(self, db: AsyncSession, status: NotificationStatus) -> Sequence[NotificationLog]:
        query = select(NotificationLog).where(NotificationLog.status == status)
        result = await db.execute(query)
        return result.scalars().all()
