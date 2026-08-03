"""
app/services/inventory.py

This file implements the InventoryService.
Under Clean Architecture, this resides in the Application Business Rules (Use Cases) layer.
"""

import uuid
from typing import Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, NotFoundException, ConflictException
from app.models.inventory import InventoryItem, InventoryTransaction, InventoryTransactionType
from app.schemas.inventory import InventoryItemCreate, InventoryItemUpdate, InventoryTransactionCreate
from app.repositories.inventory import InventoryItemRepository, InventoryTransactionRepository
from app.core.context import audit_context


class InventoryService:
    """
    Service layer containing business logic and orchestrating actions on Inventory.
    """

    def __init__(
        self,
        item_repo: InventoryItemRepository | None = None,
        tx_repo: InventoryTransactionRepository | None = None,
    ) -> None:
        self.item_repo = item_repo or InventoryItemRepository()
        self.tx_repo = tx_repo or InventoryTransactionRepository()

    async def create_item(self, db: AsyncSession, schema: InventoryItemCreate) -> InventoryItem:
        """
        Creates a new inventory item.
        """
        # Check uniqueness of name
        existing_name = await db.execute(
            select(InventoryItem).where(InventoryItem.name.ilike(schema.name.strip()), InventoryItem.is_deleted == False)
        )
        if existing_name.scalars().first():
            raise BadRequestException(f"Inventory item with name '{schema.name}' already exists.")

        # Check uniqueness of SKU
        existing_sku = await self.item_repo.get_by_sku(db, schema.sku)
        if existing_sku:
            raise BadRequestException(f"Inventory item with SKU '{schema.sku}' already exists.")

        item = InventoryItem(
            name=schema.name,
            sku=schema.sku,
            unit=schema.unit,
            minimum_stock=schema.minimum_stock,
            current_stock=schema.current_stock,
            supplier=schema.supplier,
            remarks=schema.remarks,
        )
        return await self.item_repo.create(db, item)

    async def get_item_by_id(self, db: AsyncSession, id: uuid.UUID) -> InventoryItem:
        """
        Retrieves an inventory item by ID.
        """
        item = await self.item_repo.get_by_id(db, id)
        if not item:
            raise NotFoundException(f"Inventory item with ID '{id}' was not found.")
        return item

    async def get_all_items(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> Sequence[InventoryItem]:
        """
        Retrieves a paginated list of inventory items.
        """
        return await self.item_repo.get_all(db, skip=skip, limit=limit)

    async def search_items(
        self, db: AsyncSession, name: str | None = None, sku: str | None = None, skip: int = 0, limit: int = 100
    ) -> Sequence[InventoryItem]:
        """
        Searches inventory items using name and/or SKU filters.
        """
        return await self.item_repo.search(db, name=name, sku=sku, skip=skip, limit=limit)

    async def update_item(self, db: AsyncSession, id: uuid.UUID, schema: InventoryItemUpdate) -> InventoryItem:
        """
        Updates an inventory item, verifying the optimistic lock version.
        """
        item = await self.item_repo.get_by_id(db, id)
        if not item:
            raise NotFoundException(f"Inventory item with ID '{id}' was not found.")

        # Optimistic lock check
        if schema.version is not None and item.version != schema.version:
            raise ConflictException("Inventory item was modified by another process. Please reload.")

        update_data = schema.model_dump(exclude_unset=True)
        update_data.pop("version", None)

        # Check unique name if name is updated
        new_name = update_data.get("name")
        if new_name and new_name.lower() != item.name.lower():
            existing_name = await db.execute(
                select(InventoryItem).where(InventoryItem.name.ilike(new_name.strip()), InventoryItem.is_deleted == False)
            )
            if existing_name.scalars().first():
                raise BadRequestException(f"Inventory item with name '{new_name}' already exists.")

        # Check unique SKU if SKU is updated
        new_sku = update_data.get("sku")
        if new_sku and new_sku.lower() != item.sku.lower():
            existing_sku = await self.item_repo.get_by_sku(db, new_sku)
            if existing_sku:
                raise BadRequestException(f"Inventory item with SKU '{new_sku}' already exists.")

        return await self.item_repo.update(db, db_obj=item, update_data=update_data)

    async def delete_item(self, db: AsyncSession, id: uuid.UUID) -> None:
        """
        Soft-deletes an inventory item.
        """
        item = await self.item_repo.get_by_id(db, id)
        if not item:
            raise NotFoundException(f"Inventory item with ID '{id}' was not found.")
        await self.item_repo.delete(db, db_obj=item)

    async def record_transaction(self, db: AsyncSession, schema: InventoryTransactionCreate) -> InventoryTransaction:
        """
        Performs stock changes inside a transactional database lock.
        """
        # 1. Lock the inventory item row to prevent concurrency races on current_stock calculations
        query = select(InventoryItem).where(InventoryItem.id == schema.inventory_item_id, InventoryItem.is_deleted == False).with_for_update()
        result = await db.execute(query)
        item = result.scalar_one_or_none()
        if not item:
            raise NotFoundException(f"Inventory item with ID '{schema.inventory_item_id}' was not found.")

        # 2. Update stock based on type
        qty = schema.quantity
        if schema.transaction_type == InventoryTransactionType.IN:
            item.current_stock += qty
        elif schema.transaction_type == InventoryTransactionType.OUT:
            if item.current_stock < qty:
                raise BadRequestException(f"Insufficient stock for item '{item.name}'. Current: {item.current_stock}, Requested: {qty}.")
            item.current_stock -= qty
        elif schema.transaction_type == InventoryTransactionType.ADJUSTMENT:
            new_stock = item.current_stock + qty
            if new_stock < 0:
                raise BadRequestException(f"Invalid stock adjustment. Stock level cannot become negative (Current: {item.current_stock}, Adjustment: {qty}).")
            item.current_stock = new_stock

        db.add(item)

        # 3. Retrieve request context for performer
        ctx = audit_context.get()
        performed_by = ctx.get("user_id") if ctx else "SYSTEM"

        transaction = InventoryTransaction(
            inventory_item_id=schema.inventory_item_id,
            transaction_type=schema.transaction_type,
            quantity=qty,
            reason=schema.reason,
            performed_by=performed_by,
        )

        db_tx = await self.tx_repo.create(db, transaction=transaction, commit=False)
        
        # Flush and commit atomically
        await db.flush()
        await db.commit()
        await db.refresh(db_tx)
        return db_tx

    async def get_item_transactions(self, db: AsyncSession, item_id: uuid.UUID, skip: int = 0, limit: int = 100) -> Sequence[InventoryTransaction]:
        """
        Retrieves transactional history for a specific item.
        """
        await self.get_item_by_id(db, item_id)
        return await self.tx_repo.get_all_by_item_id(db, item_id, skip=skip, limit=limit)
