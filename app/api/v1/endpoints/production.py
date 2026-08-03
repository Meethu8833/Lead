"""
app/api/v1/endpoints/production.py

This file defines the API routes (Endpoints) for the Production Workflow.
It handles retrieving the dashboard, filtering order items, and updating production details.
"""

import uuid
from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_order_item_service
from app.models.order_item import ProductionStage
from app.schemas.order_item import (
    OrderItemResponse,
    ProductionStageUpdate,
    EmployeeAssignment,
    ProductionNotesUpdate,
    ProductionDashboardResponse
)
from app.services.order_item import OrderItemService

router = APIRouter()


@router.get(
    "/production/dashboard",
    response_model=ProductionDashboardResponse,
    status_code=status.HTTP_200_OK,
    summary="Get production dashboard",
    description="Calculates metrics for the production dashboard: item stage distribution, delayed items, ready items, and items delivered today."
)
async def get_production_dashboard(
    db: AsyncSession = Depends(get_db),
    service: OrderItemService = Depends(get_order_item_service),
) -> ProductionDashboardResponse:
    return await service.get_production_dashboard(db=db)


@router.get(
    "/production/stage/{stage}",
    response_model=List[OrderItemResponse],
    status_code=status.HTTP_200_OK,
    summary="Get items by stage",
    description="Retrieves a list of order items currently at a specific production stage."
)
async def get_items_by_stage(
    stage: ProductionStage,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    service: OrderItemService = Depends(get_order_item_service),
) -> List[OrderItemResponse]:
    return await service.get_items_by_stage(db=db, stage=stage, skip=skip, limit=limit)


@router.get(
    "/production/employee/{employee_id}",
    response_model=List[OrderItemResponse],
    status_code=status.HTTP_200_OK,
    summary="Get items by employee",
    description="Retrieves a list of order items currently assigned to a specific employee."
)
async def get_items_by_employee(
    employee_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    service: OrderItemService = Depends(get_order_item_service),
) -> List[OrderItemResponse]:
    return await service.get_items_by_employee(db=db, employee_id=employee_id, skip=skip, limit=limit)


@router.patch(
    "/order-items/{id}/production-stage",
    response_model=OrderItemResponse,
    status_code=status.HTTP_200_OK,
    summary="Update production stage",
    description="Updates the production stage of an order item, verifying workflow constraints and updating dates."
)
async def update_production_stage(
    id: uuid.UUID,
    payload: ProductionStageUpdate,
    db: AsyncSession = Depends(get_db),
    service: OrderItemService = Depends(get_order_item_service),
) -> OrderItemResponse:
    return await service.update_production_stage(
        db=db, id=id, stage=payload.production_stage, allow_backward=payload.allow_backward, version=payload.version
    )


@router.patch(
    "/order-items/{id}/assign",
    response_model=OrderItemResponse,
    status_code=status.HTTP_200_OK,
    summary="Assign employee",
    description="Assigns a staff member/employee to the order item."
)
async def assign_employee(
    id: uuid.UUID,
    payload: EmployeeAssignment,
    db: AsyncSession = Depends(get_db),
    service: OrderItemService = Depends(get_order_item_service),
) -> OrderItemResponse:
    return await service.assign_employee(db=db, id=id, employee_id=payload.employee_id)


@router.patch(
    "/order-items/{id}/production-notes",
    response_model=OrderItemResponse,
    status_code=status.HTTP_200_OK,
    summary="Update production notes",
    description="Updates the production-specific internal notes for an order item."
)
async def update_production_notes(
    id: uuid.UUID,
    payload: ProductionNotesUpdate,
    db: AsyncSession = Depends(get_db),
    service: OrderItemService = Depends(get_order_item_service),
) -> OrderItemResponse:
    return await service.update_production_notes(db=db, id=id, notes=payload.production_notes)
