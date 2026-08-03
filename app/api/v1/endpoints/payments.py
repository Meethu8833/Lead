"""
app/api/v1/endpoints/payments.py

API endpoints for Payment.
"""

import uuid
from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps import get_payment_service
from app.schemas.payment import PaymentCreate, PaymentUpdate, PaymentResponse
from app.services.payment import PaymentService

router = APIRouter()


@router.post(
    "/orders/{order_id}/payments",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new payment for an order",
    description="Registers a payment received for an order. Recalculates totals and checks for overpayment."
)
async def create_payment(
    order_id: uuid.UUID,
    schema: PaymentCreate,
    db: AsyncSession = Depends(get_db),
    service: PaymentService = Depends(get_payment_service),
) -> PaymentResponse:
    return await service.create_payment(db=db, order_id=order_id, schema=schema)


@router.get(
    "/orders/{order_id}/payments",
    response_model=List[PaymentResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve payments of an order"
)
async def get_payments_by_order(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: PaymentService = Depends(get_payment_service),
) -> List[PaymentResponse]:
    return await service.get_payments_by_order(db=db, order_id=order_id)


@router.get(
    "/payments",
    response_model=List[PaymentResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve all payments"
)
async def get_all_payments(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    service: PaymentService = Depends(get_payment_service),
) -> List[PaymentResponse]:
    return await service.get_all_payments(db=db, skip=skip, limit=limit)


@router.get(
    "/payments/{id}",
    response_model=PaymentResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve a payment by ID"
)
async def get_payment_by_id(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: PaymentService = Depends(get_payment_service),
) -> PaymentResponse:
    return await service.get_payment_by_id(db=db, id=id)


@router.put(
    "/payments/{id}",
    response_model=PaymentResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a payment"
)
async def update_payment(
    id: uuid.UUID,
    schema: PaymentUpdate,
    db: AsyncSession = Depends(get_db),
    service: PaymentService = Depends(get_payment_service),
) -> PaymentResponse:
    return await service.update_payment(db=db, id=id, schema=schema)


@router.delete(
    "/payments/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a payment"
)
async def delete_payment(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: PaymentService = Depends(get_payment_service),
) -> None:
    await service.delete_payment(db=db, id=id)
