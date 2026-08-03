"""
app/repositories/invoice.py

Repository for Invoice database operations.
"""

import uuid
from typing import Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.invoice import Invoice, InvoiceStatus


class InvoiceRepository:
    async def create(self, db: AsyncSession, invoice: Invoice, commit: bool = True) -> Invoice:
        db.add(invoice)
        if commit:
            await db.commit()
            await db.refresh(invoice)
        return invoice

    async def update(self, db: AsyncSession, db_obj: Invoice, update_data: dict, commit: bool = True) -> Invoice:
        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)
        db.add(db_obj)
        if commit:
            await db.commit()
            await db.refresh(db_obj)
        return db_obj

    async def delete(self, db: AsyncSession, db_obj: Invoice, commit: bool = True) -> bool:
        await db.delete(db_obj)
        if commit:
            await db.commit()
        return True

    async def get_by_id(self, db: AsyncSession, id: uuid.UUID) -> Invoice | None:
        return await db.get(Invoice, id)

    async def get_all(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> Sequence[Invoice]:
        query = select(Invoice).offset(skip).limit(limit)
        result = await db.execute(query)
        return result.scalars().all()

    async def get_by_order_id(self, db: AsyncSession, order_id: uuid.UUID) -> Sequence[Invoice]:
        query = select(Invoice).where(Invoice.order_id == order_id)
        result = await db.execute(query)
        return result.scalars().all()

    async def get_active_by_order_id(self, db: AsyncSession, order_id: uuid.UUID) -> Invoice | None:
        """
        Retrieves the active (non-cancelled) invoice for an order.
        Only one active invoice is allowed per order.
        """
        query = select(Invoice).where(
            Invoice.order_id == order_id,
            Invoice.status != InvoiceStatus.CANCELLED
        )
        result = await db.execute(query)
        return result.scalars().first()

    async def get_latest_invoice_for_year(self, db: AsyncSession, year: int) -> Invoice | None:
        """
        Retrieves the latest invoice generated in a year to determine sequence numbers.
        """
        query = (
            select(Invoice)
            .where(Invoice.invoice_number.like(f"INV-{year}-%"))
            .order_by(Invoice.invoice_number.desc())
        )
        result = await db.execute(query)
        return result.scalars().first()
