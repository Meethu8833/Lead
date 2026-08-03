"""
app/repositories/payment.py

Repository for Payment database operations.
"""

import uuid
from typing import Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.payment import Payment


class PaymentRepository:
    async def create(self, db: AsyncSession, payment: Payment, commit: bool = True) -> Payment:
        db.add(payment)
        if commit:
            await db.commit()
            await db.refresh(payment)
        return payment

    async def update(self, db: AsyncSession, db_obj: Payment, update_data: dict, commit: bool = True) -> Payment:
        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)
        db.add(db_obj)
        if commit:
            await db.commit()
            await db.refresh(db_obj)
        return db_obj

    async def delete(self, db: AsyncSession, db_obj: Payment, commit: bool = True) -> bool:
        await db.delete(db_obj)
        if commit:
            await db.commit()
        return True

    async def get_by_id(self, db: AsyncSession, id: uuid.UUID) -> Payment | None:
        return await db.get(Payment, id)

    async def get_all(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> Sequence[Payment]:
        query = select(Payment).offset(skip).limit(limit)
        result = await db.execute(query)
        return result.scalars().all()

    async def get_by_order_id(self, db: AsyncSession, order_id: uuid.UUID) -> Sequence[Payment]:
        query = select(Payment).where(Payment.order_id == order_id)
        result = await db.execute(query)
        return result.scalars().all()
