"""
app/api/v1/endpoints/leads.py

This file defines the API routes (Endpoints) for the Lead module.
Under Clean Architecture, this file resides in the Interface Adapters layer.
It acts as the HTTP controller: parsing requests, delegating execution to the Service layer,
and returning structured JSON responses matching our Pydantic schemas.

All database operations are mediated by the service, ensuring routes contain zero business logic.
Every route is protected by RBAC via `RequirePermission`, matching the module:action convention
already established elsewhere in this codebase (see app/api/deps.py).
"""

import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_lead_service, RequirePermission
from app.models.lead import LeadStatus, LeadSource
from app.schemas.lead import (
    LeadCreate,
    LeadUpdate,
    LeadResponse,
    LeadListResponse,
)
from app.services.lead import LeadService

router = APIRouter()


@router.post(
    "",
    response_model=LeadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new lead",
    description="Registers a new lead in the acquisition pipeline. Phone numbers must be unique. Status is always initialized to NEW.",
    dependencies=[Depends(RequirePermission("leads:create"))],
)
async def create_lead(
    schema: LeadCreate,
    db: AsyncSession = Depends(get_db),
    service: LeadService = Depends(get_lead_service),
) -> LeadResponse:
    """
    POST /leads Endpoint Flow:
    Client JSON -> Validation -> Injects DB & Service -> Calls Service -> Returns created lead.
    """
    return await service.create_lead(db=db, schema=schema)


@router.get(
    "",
    response_model=LeadListResponse,
    status_code=status.HTTP_200_OK,
    summary="List/search/filter leads",
    description=(
        "Fetches a paginated list of leads. Supports filtering by status, source, district, city, "
        "assigned employee, and created date range, plus a free-text search keyword across "
        "business_name, contact_person, phone, whatsapp, and email."
    ),
    dependencies=[Depends(RequirePermission("leads:view"))],
)
async def get_leads(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    status_filter: LeadStatus | None = Query(None, alias="status", description="Filter by lead status"),
    source: LeadSource | None = Query(None, description="Filter by lead source"),
    district: str | None = Query(None, description="Filter by district (partial match)"),
    city: str | None = Query(None, description="Filter by city (partial match)"),
    assigned_employee_id: uuid.UUID | None = Query(None, description="Filter by assigned employee"),
    created_from: datetime | None = Query(None, description="Filter by created_at >= this timestamp"),
    created_to: datetime | None = Query(None, description="Filter by created_at <= this timestamp"),
    search: str | None = Query(None, description="Search keyword across business_name, contact_person, phone, whatsapp, email"),
    db: AsyncSession = Depends(get_db),
    service: LeadService = Depends(get_lead_service),
) -> LeadListResponse:
    """
    GET /leads Endpoint Flow:
    Client HTTP -> Service -> Repository -> Returns paginated, filtered list of leads + total count.
    """
    items, total = await service.get_all_leads(
        db=db,
        skip=skip,
        limit=limit,
        status=status_filter,
        source=source,
        district=district,
        city=city,
        assigned_employee_id=assigned_employee_id,
        created_from=created_from,
        created_to=created_to,
        search=search,
    )
    return LeadListResponse(items=items, total=total, skip=skip, limit=limit)


@router.get(
    "/{id}",
    response_model=LeadResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve a lead by ID",
    description="Retrieves details of a lead matching the given UUID. Raises 404 if not found.",
    dependencies=[Depends(RequirePermission("leads:view"))],
)
async def get_lead(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: LeadService = Depends(get_lead_service),
) -> LeadResponse:
    """
    GET /leads/{id} Endpoint Flow:
    Retrieves a single lead by UUID.
    """
    return await service.get_lead_by_id(db=db, id=id)


@router.put(
    "/{id}",
    response_model=LeadResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a lead",
    description="Updates existing lead details. Partially specified fields are ignored. Enforces optimistic locking via `version`.",
    dependencies=[Depends(RequirePermission("leads:update"))],
)
async def update_lead(
    id: uuid.UUID,
    schema: LeadUpdate,
    db: AsyncSession = Depends(get_db),
    service: LeadService = Depends(get_lead_service),
) -> LeadResponse:
    """
    PUT /leads/{id} Endpoint Flow:
    Updates lead details, validating uniqueness and optimistic lock version.
    """
    return await service.update_lead(db=db, id=id, schema=schema)


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a lead",
    description="Soft deletes a lead. Raises 404 if not found. Deleted leads no longer appear in normal queries.",
    dependencies=[Depends(RequirePermission("leads:delete"))],
)
async def delete_lead(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: LeadService = Depends(get_lead_service),
) -> None:
    """
    DELETE /leads/{id} Endpoint Flow:
    Soft deletes a lead. Raises 404 if not found.
    """
    await service.delete_lead(db=db, id=id)
