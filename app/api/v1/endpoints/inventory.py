"""
app/api/v1/endpoints/inventory.py

This file defines the API routes (Endpoints) for the Inventory catalog and stock movements.
Under Clean Architecture, this resides in the API Layer (Interface Adapters).
"""

import uuid
from typing import List
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_inventory_service
from app.schemas.inventory import (
    InventoryItemCreate,
    InventoryItemUpdate,
    InventoryItemResponse,
    InventoryTransactionCreate,
    InventoryTransactionResponse,
)
from app.services.inventory import InventoryService

router = APIRouter()


@router.post(
    "/items",
    response_model=InventoryItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new inventory item",
    description="Registers a new physical item in the inventory catalog. Enforces uniqueness of name and SKU."
)
async def create_item(
    schema: InventoryItemCreate,
    db: AsyncSession = Depends(get_db),
    service: InventoryService = Depends(get_inventory_service),
) -> InventoryItemResponse:
    return await service.create_item(db=db, schema=schema)


@router.get(
    "/items",
    response_model=List[InventoryItemResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve all inventory items",
    description="Fetches a paginated list of active inventory items."
)
async def get_items(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    service: InventoryService = Depends(get_inventory_service),
) -> List[InventoryItemResponse]:
    return await service.get_all_items(db=db, skip=skip, limit=limit)


@router.get(
    "/items/search",
    response_model=List[InventoryItemResponse],
    status_code=status.HTTP_200_OK,
    summary="Search inventory items",
    description="Searches inventory items using name and/or SKU filters."
)
async def search_items(
    name: str | None = Query(None, description="Partial match for item name"),
    sku: str | None = Query(None, description="Partial match for SKU"),
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    service: InventoryService = Depends(get_inventory_service),
) -> List[InventoryItemResponse]:
    return await service.search_items(db=db, name=name, sku=sku, skip=skip, limit=limit)


@router.get(
    "/items/{id}",
    response_model=InventoryItemResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve an inventory item by ID",
    description="Retrieves inventory item details matching the given UUID."
)
async def get_item(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: InventoryService = Depends(get_inventory_service),
) -> InventoryItemResponse:
    return await service.get_item_by_id(db=db, id=id)


@router.put(
    "/items/{id}",
    response_model=InventoryItemResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an inventory item",
    description="Updates details of an inventory item. Enforces optimistic locking version checks and uniqueness."
)
async def update_item(
    id: uuid.UUID,
    schema: InventoryItemUpdate,
    db: AsyncSession = Depends(get_db),
    service: InventoryService = Depends(get_inventory_service),
) -> InventoryItemResponse:
    return await service.update_item(db=db, id=id, schema=schema)


@router.delete(
    "/items/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an inventory item",
    description="Soft deletes an inventory item from the catalog."
)
async def delete_item(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: InventoryService = Depends(get_inventory_service),
) -> None:
    await service.delete_item(db=db, id=id)


@router.post(
    "/transactions",
    response_model=InventoryTransactionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record stock movement transaction",
    description="Logs a new stock movement (IN, OUT, ADJUSTMENT), updating stock level atomically inside a lock."
)
async def record_transaction(
    schema: InventoryTransactionCreate,
    db: AsyncSession = Depends(get_db),
    service: InventoryService = Depends(get_inventory_service),
) -> InventoryTransactionResponse:
    return await service.record_transaction(db=db, schema=schema)


@router.get(
    "/items/{id}/transactions",
    response_model=List[InventoryTransactionResponse],
    status_code=status.HTTP_200_OK,
    summary="View transactions for item",
    description="Retrieves a list of stock transactions for a specific inventory item."
)
async def get_item_transactions(
    id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    service: InventoryService = Depends(get_inventory_service),
) -> List[InventoryTransactionResponse]:
    return await service.get_item_transactions(db=db, item_id=id, skip=skip, limit=limit)
