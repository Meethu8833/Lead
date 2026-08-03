"""
app/repositories/inventory.py

This file implements the InventoryItemRepository and InventoryTransactionRepository.
Under Clean Architecture, this resides in the Interface Adapters layer.
"""

import uuid
from typing import Sequence
from datetime import datetime, timezone
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.inventory import InventoryItem, InventoryTransaction


class InventoryItemRepository:
    """
    InventoryItem Repository.
    Handles CRUD operations, SKU checks, and filters for inventory items.
    """

    def __init__(self, include_deleted: bool = False) -> None:
        self.include_deleted = include_deleted

    async def create(self, db: AsyncSession, item: InventoryItem) -> InventoryItem:
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return item

    async def update(self, db: AsyncSession, db_obj: InventoryItem, update_data: dict) -> InventoryItem:
        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)
        
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def delete(self, db: AsyncSession, db_obj: InventoryItem) -> bool:
        """
        Soft deletes the inventory item.
        """
        db_obj.is_deleted = True
        db_obj.deleted_at = datetime.now(timezone.utc)
        db.add(db_obj)
        await db.commit()
        return True

    async def get_by_id(self, db: AsyncSession, id: uuid.UUID, include_deleted: bool | None = None) -> InventoryItem | None:
        inc = include_deleted if include_deleted is not None else self.include_deleted
        if inc:
            return await db.get(InventoryItem, id)
        
        query = select(InventoryItem).where(InventoryItem.id == id, InventoryItem.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().first()

    async def get_by_sku(self, db: AsyncSession, sku: str, include_deleted: bool | None = None) -> InventoryItem | None:
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(InventoryItem).where(InventoryItem.sku.ilike(sku.strip()))
        if not inc:
            query = query.where(InventoryItem.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().first()

    async def get_all(self, db: AsyncSession, skip: int = 0, limit: int = 100, include_deleted: bool | None = None) -> Sequence[InventoryItem]:
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(InventoryItem).offset(skip).limit(limit)
        if not inc:
            query = query.where(InventoryItem.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().all()

    async def search(
        self,
        db: AsyncSession,
        name: str | None = None,
        sku: str | None = None,
        skip: int = 0,
        limit: int = 100,
        include_deleted: bool | None = None,
    ) -> Sequence[InventoryItem]:
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(InventoryItem)
        filters = []
        
        if name:
            filters.append(InventoryItem.name.ilike(f"%{name.strip()}%"))
        if sku:
            filters.append(InventoryItem.sku.ilike(f"%{sku.strip()}%"))
        if not inc:
            filters.append(InventoryItem.is_deleted == False)
            
        if filters:
            query = query.where(and_(*filters))
            
        query = query.offset(skip).limit(limit)
        result = await db.execute(query)
        return result.scalars().all()


class AdminInventoryItemRepository(InventoryItemRepository):
    def __init__(self) -> None:
        super().__init__(include_deleted=True)


class InventoryTransactionRepository:
    """
    InventoryTransaction Repository.
    Handles logging and auditing of stock movements.
    """

    async def create(self, db: AsyncSession, transaction: InventoryTransaction, commit: bool = True) -> InventoryTransaction:
        db.add(transaction)
        if commit:
            await db.commit()
            await db.refresh(transaction)
        return transaction

    async def get_by_id(self, db: AsyncSession, id: uuid.UUID) -> InventoryTransaction | None:
        return await db.get(InventoryTransaction, id)

    async def get_all_by_item_id(self, db: AsyncSession, item_id: uuid.UUID, skip: int = 0, limit: int = 100) -> Sequence[InventoryTransaction]:
        query = (
            select(InventoryTransaction)
            .where(InventoryTransaction.inventory_item_id == item_id)
            .order_by(InventoryTransaction.performed_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(query)
        return result.scalars().all()

    async def get_all(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> Sequence[InventoryTransaction]:
        query = select(InventoryTransaction).order_by(InventoryTransaction.performed_at.desc()).offset(skip).limit(limit)
        result = await db.execute(query)
        return result.scalars().all()
