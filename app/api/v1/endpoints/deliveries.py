"""
app/api/v1/endpoints/deliveries.py

API endpoints for Delivery.
"""

import uuid
from typing import Sequence, List
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps import get_delivery_service
from app.schemas.delivery import DeliveryCreate, DeliveryUpdate, DeliveryResponse
from app.services.delivery import DeliveryService

router = APIRouter()


@router.post(
    "/orders/{order_id}/deliveries",
    response_model=DeliveryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create delivery details for an order"
)
async def create_delivery(
    order_id: uuid.UUID,
    schema: DeliveryCreate,
    db: AsyncSession = Depends(get_db),
    service: DeliveryService = Depends(get_delivery_service),
) -> DeliveryResponse:
    return await service.create_delivery(db=db, order_id=order_id, schema=schema)


@router.get(
    "/orders/{order_id}/deliveries",
    response_model=DeliveryResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve delivery details of an order"
)
async def get_delivery_by_order(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: DeliveryService = Depends(get_delivery_service),
) -> DeliveryResponse:
    return await service.get_delivery_by_order(db=db, order_id=order_id)


@router.get(
    "/deliveries",
    response_model=List[DeliveryResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve all deliveries"
)
async def get_all_deliveries(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    service: DeliveryService = Depends(get_delivery_service),
) -> List[DeliveryResponse]:
    return await service.get_all_deliveries(db=db, skip=skip, limit=limit)


@router.get(
    "/deliveries/{id}",
    response_model=DeliveryResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve a delivery by ID"
)
async def get_delivery_by_id(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: DeliveryService = Depends(get_delivery_service),
) -> DeliveryResponse:
    return await service.get_delivery_by_id(db=db, id=id)


@router.put(
    "/deliveries/{id}",
    response_model=DeliveryResponse,
    status_code=status.HTTP_200_OK,
    summary="Update delivery details"
)
async def update_delivery(
    id: uuid.UUID,
    schema: DeliveryUpdate,
    db: AsyncSession = Depends(get_db),
    service: DeliveryService = Depends(get_delivery_service),
) -> DeliveryResponse:
    return await service.update_delivery(db=db, id=id, schema=schema)


@router.delete(
    "/deliveries/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete delivery details"
)
async def delete_delivery(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: DeliveryService = Depends(get_delivery_service),
) -> None:
    await service.delete_delivery(db=db, id=id)
