"""
app/api/v1/endpoints/orders.py

This file defines the API routes (Endpoints) for the Order module.
Under Clean Architecture, this file resides in the Interface Adapters layer.
It acts as the HTTP controller: parsing requests, delegating execution to the Service layer,
and returning structured JSON responses matching our Pydantic schemas.

All database operations are mediated by the service, ensuring routes contain zero business logic.
"""

import uuid
from typing import List
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_order_service
from app.models.order import OrderStatus
from app.schemas.order import (
    OrderCreate,
    OrderUpdate,
    OrderResponse,
)
from app.services.order import OrderService

router = APIRouter()


class OrderStatusUpdatePayload(BaseModel):
    """
    Request payload schema for updating order status.
    """
    status: OrderStatus = Field(..., description="The target workflow status of the order")


@router.post(
    "",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new order",
    description="Creates a new lab order for a photographer. Computes order number and balance amount automatically."
)
async def create_order(
    schema: OrderCreate,
    db: AsyncSession = Depends(get_db),
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    """
    POST /orders Endpoint Flow:
    Client JSON -> Validation -> Injects DB & Service -> Calls Service -> Auto-generates ID & Order Number -> Returns JSON.
    """
    return await service.create_order(db=db, schema=schema)


@router.get(
    "",
    response_model=List[OrderResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve all orders",
    description="Fetches a paginated list of all orders registered in the system."
)
async def get_orders(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    service: OrderService = Depends(get_order_service),
) -> List[OrderResponse]:
    """
    GET /orders Endpoint Flow:
    Client HTTP -> Service -> Repository -> Returns list of order records.
    """
    return await service.get_all_orders(db=db, skip=skip, limit=limit)


@router.get(
    "/search",
    response_model=List[OrderResponse],
    status_code=status.HTTP_200_OK,
    summary="Search orders",
    description="Searches orders using filters on order_number, job_name, and status. Case-insensitive partial matching is supported."
)
async def search_orders(
    order_number: str | None = None,
    job_name: str | None = None,
    status: OrderStatus | None = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    service: OrderService = Depends(get_order_service),
) -> List[OrderResponse]:
    """
    GET /orders/search Endpoint Flow:
    Searches orders using query parameters.
    """
    return await service.search_orders(
        db=db,
        order_number=order_number,
        job_name=job_name,
        status=status,
        skip=skip,
        limit=limit
    )


@router.get(
    "/photographer/{photographer_id}",
    response_model=List[OrderResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve orders by photographer ID",
    description="Fetches all orders placed by the specified photographer."
)
async def get_orders_by_photographer(
    photographer_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    service: OrderService = Depends(get_order_service),
) -> List[OrderResponse]:
    """
    GET /orders/photographer/{photographer_id} Endpoint Flow:
    Retrieves photographer's list of orders. Raises 404 if the photographer does not exist.
    """
    return await service.get_orders_by_photographer(
        db=db, photographer_id=photographer_id, skip=skip, limit=limit
    )


@router.get(
    "/{id}",
    response_model=OrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve an order by ID",
    description="Retrieves details of an order matching the given UUID. Raises 404 if not found."
)
async def get_order(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    """
    GET /orders/{id} Endpoint Flow:
    Retrieves a single order by UUID.
    """
    return await service.get_order_by_id(db=db, id=id)


@router.put(
    "/{id}",
    response_model=OrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an order",
    description="Updates existing order details. Partially specified fields are processed, and financials or delivery dates are updated based on business logic."
)
async def update_order(
    id: uuid.UUID,
    schema: OrderUpdate,
    db: AsyncSession = Depends(get_db),
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    """
    PUT /orders/{id} Endpoint Flow:
    Updates order details. Recomputes financials and dates as needed.
    """
    return await service.update_order(db=db, id=id, schema=schema)


@router.patch(
    "/{id}/status",
    response_model=OrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Update order status",
    description="Updates the status of an order. Enforces business logic changes like setting delivered_at."
)
async def update_order_status(
    id: uuid.UUID,
    payload: OrderStatusUpdatePayload,
    db: AsyncSession = Depends(get_db),
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    """
    PATCH /orders/{id}/status Endpoint Flow:
    Updates status and returns order.
    """
    return await service.update_status(db=db, id=id, status=payload.status)


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an order",
    description="Deletes an order from the database. Deleting orders that have a status of DELIVERED is blocked."
)
async def delete_order(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: OrderService = Depends(get_order_service),
) -> None:
    """
    DELETE /orders/{id} Endpoint Flow:
    Deletes an order. Raises 400 if order is already delivered.
    """
    await service.delete_order(db=db, id=id)
