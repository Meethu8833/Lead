"""
app/repositories/delivery.py

Repository for Delivery database operations.
"""

import uuid
from typing import Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.delivery import Delivery


class DeliveryRepository:
    async def create(self, db: AsyncSession, delivery: Delivery, commit: bool = True) -> Delivery:
        db.add(delivery)
        if commit:
            await db.commit()
            await db.refresh(delivery)
        return delivery

    async def update(self, db: AsyncSession, db_obj: Delivery, update_data: dict, commit: bool = True) -> Delivery:
        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)
        db.add(db_obj)
        if commit:
            await db.commit()
            await db.refresh(db_obj)
        return db_obj

    async def delete(self, db: AsyncSession, db_obj: Delivery, commit: bool = True) -> bool:
        await db.delete(db_obj)
        if commit:
            await db.commit()
        return True

    async def get_by_id(self, db: AsyncSession, id: uuid.UUID) -> Delivery | None:
        return await db.get(Delivery, id)

    async def get_all(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> Sequence[Delivery]:
        query = select(Delivery).offset(skip).limit(limit)
        result = await db.execute(query)
        return result.scalars().all()

    async def get_by_order_id(self, db: AsyncSession, order_id: uuid.UUID) -> Delivery | None:
        query = select(Delivery).where(Delivery.order_id == order_id)
        result = await db.execute(query)
        return result.scalars().first()
