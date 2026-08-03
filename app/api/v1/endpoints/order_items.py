"""
app/api/v1/endpoints/order_items.py

This file defines the API routes (Endpoints) for the OrderItem entity.
Under Clean Architecture, this file resides in the API Layer (Interface Adapters).
It handles parsing requests, invoking the OrderItemService, and returning Pydantic responses.
"""

import uuid
from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_order_item_service
from app.schemas.order_item import OrderItemCreate, OrderItemUpdate, OrderItemResponse
from app.services.order_item import OrderItemService

router = APIRouter()


@router.post(
    "/orders/{order_id}/items",
    response_model=OrderItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add an item to an order",
    description="Creates a new OrderItem line for the specified order. Recalculates order total and balance amount automatically."
)
async def create_order_item(
    order_id: uuid.UUID,
    schema: OrderItemCreate,
    db: AsyncSession = Depends(get_db),
    service: OrderItemService = Depends(get_order_item_service),
) -> OrderItemResponse:
    return await service.create_item(db=db, order_id=order_id, schema=schema)


@router.get(
    "/orders/{order_id}/items",
    response_model=List[OrderItemResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve all items for an order",
    description="Fetches a paginated list of all item lines belonging to the specified order."
)
async def get_order_items(
    order_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    service: OrderItemService = Depends(get_order_item_service),
) -> List[OrderItemResponse]:
    return await service.get_items_by_order(db=db, order_id=order_id, skip=skip, limit=limit)


@router.put(
    "/order-items/{id}",
    response_model=OrderItemResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an order item",
    description="Updates details of an order item (such as quantity or discount). Triggers recalculation of parent order total."
)
async def update_order_item(
    id: uuid.UUID,
    schema: OrderItemUpdate,
    db: AsyncSession = Depends(get_db),
    service: OrderItemService = Depends(get_order_item_service),
) -> OrderItemResponse:
    return await service.update_item(db=db, id=id, schema=schema)


@router.delete(
    "/order-items/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an order item",
    description="Removes an item line from an order. Triggers recalculation of parent order total."
)
async def delete_order_item(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: OrderItemService = Depends(get_order_item_service),
) -> None:
    await service.delete_item(db=db, id=id)
