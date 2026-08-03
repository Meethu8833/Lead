"""
tests/test_inventory.py

Integration tests for the Inventory module.
Verifies:
1. InventoryItem CRUD & validation.
2. Optimistic locking version checking on update.
3. Stock transactions (IN, OUT, ADJUSTMENT) with automatic stock recalculation.
4. Validation blocks (e.g. Insufficient stock on OUT, negative stock on ADJUSTMENT).
5. Performed_by auditing via request context.
6. Soft deletion.
"""

import asyncio
import sys
import os
import uuid
import random
from sqlalchemy import select

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.core.context import audit_context
from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.models.inventory import InventoryItem, InventoryTransaction, InventoryTransactionType
from app.schemas.inventory import (
    InventoryItemCreate,
    InventoryItemUpdate,
    InventoryTransactionCreate,
)
from app.services.inventory import InventoryService


async def test_inventory():
    print("=== STARTING INVENTORY INTEGRATION TESTS ===")
    
    # Initialize context
    user_id = str(uuid.uuid4())
    audit_context.set({
        "user_id": user_id,
        "ip_address": "127.0.0.1",
        "user_agent": "Test Client"
    })

    service = InventoryService()

    async with AsyncSessionLocal() as db:
        try:
            print("\n--- [1] TESTING ITEM CREATION ---")
            rand_suffix = str(uuid.uuid4())[:8]
            item_name = f"Glossy Photo Paper {rand_suffix}"
            item_sku = f"SKU-GLOSSY-{rand_suffix}"
            
            schema = InventoryItemCreate(
                name=item_name,
                sku=item_sku,
                unit="pack",
                minimum_stock=10,
                current_stock=50,
                supplier="Kodak Lab Supply"
            )
            item = await service.create_item(db, schema)
            assert item.id is not None
            assert item.name == item_name
            assert item.current_stock == 50
            assert item.version == 1
            print(f"Created item successfully: {item.name} (SKU: {item.sku})")

            # Verify uniqueness check
            try:
                await service.create_item(db, schema)
                assert False, "Duplicate item creation did not raise BadRequestException"
            except BadRequestException as e:
                print(f"Duplicate item check passed: {e}")

            print("\n--- [2] TESTING OPTIMISTIC LOCKING ---")
            # Successful update
            update_schema = InventoryItemUpdate(
                remarks="Updated remarks",
                version=item.version
            )
            item = await service.update_item(db, item.id, update_schema)
            assert item.remarks == "Updated remarks"
            assert item.version == 2
            print("Successful update incremented version correctly.")

            # Mismatched version update
            conflict_schema = InventoryItemUpdate(
                remarks="Conflicting remarks",
                version=1  # Stale version
            )
            try:
                await service.update_item(db, item.id, conflict_schema)
                assert False, "Stale version update did not raise ConflictException"
            except ConflictException as e:
                print(f"Optimistic lock conflict check passed: {e}")

            print("\n--- [3] TESTING STOCK MOVEMENTS (IN/OUT) ---")
            # 1. IN Transaction
            tx_in_schema = InventoryTransactionCreate(
                inventory_item_id=item.id,
                transaction_type=InventoryTransactionType.IN,
                quantity=20,
                reason="Restock shipment received"
            )
            tx_in = await service.record_transaction(db, tx_in_schema)
            
            # Reload item to check stock
            await db.refresh(item)
            assert item.current_stock == 70
            assert tx_in.performed_by == user_id
            print(f"IN transaction success. Stock: {item.current_stock}")

            # 2. OUT Transaction
            tx_out_schema = InventoryTransactionCreate(
                inventory_item_id=item.id,
                transaction_type=InventoryTransactionType.OUT,
                quantity=15,
                reason="Items dispatched for Order #1"
            )
            tx_out = await service.record_transaction(db, tx_out_schema)
            await db.refresh(item)
            assert item.current_stock == 55
            print(f"OUT transaction success. Stock: {item.current_stock}")

            # 3. Insufficient OUT Transaction
            tx_out_insufficient = InventoryTransactionCreate(
                inventory_item_id=item.id,
                transaction_type=InventoryTransactionType.OUT,
                quantity=100,  # Exceeds current stock 55
                reason="Excessive request"
            )
            try:
                await service.record_transaction(db, tx_out_insufficient)
                assert False, "Insufficient stock did not raise BadRequestException"
            except BadRequestException as e:
                print(f"Insufficient stock check passed: {e}")

            print("\n--- [4] TESTING ADJUSTMENTS ---")
            # Positive adjustment
            tx_adj_pos = InventoryTransactionCreate(
                inventory_item_id=item.id,
                transaction_type=InventoryTransactionType.ADJUSTMENT,
                quantity=5,
                reason="Cycle count correction (+5)"
            )
            await service.record_transaction(db, tx_adj_pos)
            await db.refresh(item)
            assert item.current_stock == 60
            print(f"Positive ADJUSTMENT success. Stock: {item.current_stock}")

            # Negative adjustment
            tx_adj_neg = InventoryTransactionCreate(
                inventory_item_id=item.id,
                transaction_type=InventoryTransactionType.ADJUSTMENT,
                quantity=-10,
                reason="Damaged goods write-off (-10)"
            )
            await service.record_transaction(db, tx_adj_neg)
            await db.refresh(item)
            assert item.current_stock == 50
            print(f"Negative ADJUSTMENT success. Stock: {item.current_stock}")

            # Invalid negative adjustment (resulting in negative stock)
            tx_adj_invalid = InventoryTransactionCreate(
                inventory_item_id=item.id,
                transaction_type=InventoryTransactionType.ADJUSTMENT,
                quantity=-60,  # Stock is 50
                reason="Invalid adjustment"
            )
            try:
                await service.record_transaction(db, tx_adj_invalid)
                assert False, "Adjustment resulting in negative stock did not raise BadRequestException"
            except BadRequestException as e:
                print(f"Invalid negative stock adjustment check passed: {e}")

            print("\n--- [5] TESTING TRANSACTIONS HISTORY & DELETE ---")
            history = await service.get_item_transactions(db, item.id)
            # Should have 4 successful transactions: IN, OUT, ADJUSTMENT(+5), ADJUSTMENT(-10)
            assert len(history) == 4
            print(f"Retrieved {len(history)} transaction logs for this item.")

            # Soft delete item
            await service.delete_item(db, item.id)
            
            # Fetch by ID (should throw NotFoundException now)
            try:
                await service.get_item_by_id(db, item.id)
                assert False, "Soft deleted item retrieved without include_deleted flag"
            except NotFoundException as e:
                print(f"Soft delete check passed: {e}")

            print("\n=== ALL INVENTORY INTEGRATION TESTS COMPLETED SUCCESSFULLY ===")

        finally:
            await db.rollback()
            print("Database transaction rolled back.")


if __name__ == "__main__":
    asyncio.run(test_inventory())
