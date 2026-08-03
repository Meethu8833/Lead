"""
app/api/v1/endpoints/invoices.py

API endpoints for Invoice.
"""

import uuid
from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps import get_invoice_service
from app.schemas.invoice import InvoiceCreate, InvoiceUpdate, InvoiceResponse
from app.services.invoice import InvoiceService

router = APIRouter()


@router.post(
    "/orders/{order_id}/invoices",
    response_model=InvoiceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new invoice for an order",
    description="Generates an invoice snapshot for an order. Locks catalog prices."
)
async def create_invoice(
    order_id: uuid.UUID,
    schema: InvoiceCreate,
    db: AsyncSession = Depends(get_db),
    service: InvoiceService = Depends(get_invoice_service),
) -> InvoiceResponse:
    return await service.create_invoice(db=db, order_id=order_id, schema=schema)


@router.get(
    "/orders/{order_id}/invoices",
    response_model=List[InvoiceResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve invoices of an order"
)
async def get_invoices_by_order(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: InvoiceService = Depends(get_invoice_service),
) -> List[InvoiceResponse]:
    return await service.get_invoices_by_order(db=db, order_id=order_id)


@router.get(
    "/invoices",
    response_model=List[InvoiceResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve all invoices"
)
async def get_all_invoices(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    service: InvoiceService = Depends(get_invoice_service),
) -> List[InvoiceResponse]:
    return await service.get_all_invoices(db=db, skip=skip, limit=limit)


@router.get(
    "/invoices/{id}",
    response_model=InvoiceResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve an invoice by ID"
)
async def get_invoice_by_id(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: InvoiceService = Depends(get_invoice_service),
) -> InvoiceResponse:
    return await service.get_invoice_by_id(db=db, id=id)


@router.put(
    "/invoices/{id}",
    response_model=InvoiceResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an invoice"
)
async def update_invoice(
    id: uuid.UUID,
    schema: InvoiceUpdate,
    db: AsyncSession = Depends(get_db),
    service: InvoiceService = Depends(get_invoice_service),
) -> InvoiceResponse:
    return await service.update_invoice(db=db, id=id, schema=schema)


@router.delete(
    "/invoices/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an invoice"
)
async def delete_invoice(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: InvoiceService = Depends(get_invoice_service),
) -> None:
    await service.delete_invoice(db=db, id=id)
