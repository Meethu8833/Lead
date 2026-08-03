"""
app/api/v1/endpoints/photographers.py

This file defines the API routes (Endpoints) for the Photographer module.
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

from app.api.deps import get_db, get_photographer_service
from app.models.photographer import LeadStatus
from app.schemas.photographer import (
    PhotographerCreate,
    PhotographerUpdate,
    PhotographerResponse,
)
from app.services.photographer import PhotographerService

router = APIRouter()


class StatusUpdatePayload(BaseModel):
    """
    Request payload schema for updating lead status.
    """
    status: LeadStatus = Field(..., description="The target CRM lead status")


class NotesUpdatePayload(BaseModel):
    """
    Request payload schema for updating internal CRM notes.
    """
    internal_notes: str = Field(..., description="The new internal notes content")


@router.post(
    "",
    response_model=PhotographerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new photographer",
    description="Registers a new photographer in the CRM system. Phone numbers must be unique."
)
async def create_photographer(
    schema: PhotographerCreate,
    db: AsyncSession = Depends(get_db),
    service: PhotographerService = Depends(get_photographer_service),
) -> PhotographerResponse:
    """
    POST Request Flow:
    Client HTTP Request -> Endpoint Handler -> Injects Session & Service -> Calls service.create_photographer ->
    Validates rules -> Calls repository.create -> Commits to Database -> Serializes to Pydantic Response.
    """
    return await service.create_photographer(db=db, schema=schema)


@router.get(
    "",
    response_model=List[PhotographerResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve all photographers",
    description="Fetches a paginated list of all photographers registered in the CRM."
)
async def get_photographers(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    service: PhotographerService = Depends(get_photographer_service),
) -> List[PhotographerResponse]:
    """
    GET /photographers Flow:
    FastAPI Route -> Injects deps -> Service.get_all_photographers -> Repository.get_all -> Returns list of models.
    """
    return await service.get_all_photographers(db=db, skip=skip, limit=limit)


# ==========================================
# CRM LEAD MANAGEMENT ENDPOINTS
# ==========================================

@router.get(
    "/search",
    response_model=List[PhotographerResponse],
    status_code=status.HTTP_200_OK,
    summary="Search photographers/leads",
    description="Searches photographers using case-insensitive partial matches on name, phone, city, or studio_name."
)
async def search_photographers(
    name: str | None = None,
    phone: str | None = None,
    city: str | None = None,
    studio: str | None = None,
    studio_name: str | None = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    service: PhotographerService = Depends(get_photographer_service),
) -> List[PhotographerResponse]:
    """
    GET /photographers/search
    """
    resolved_studio = studio_name or studio
    return await service.search_photographers(
        db=db,
        name=name,
        phone=phone,
        city=city,
        studio_name=resolved_studio,
        skip=skip,
        limit=limit
    )


@router.get(
    "/followups",
    response_model=List[PhotographerResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve due follow-ups",
    description="Fetches photographers whose scheduled next follow-up date is in the past."
)
async def get_followups(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    service: PhotographerService = Depends(get_photographer_service),
) -> List[PhotographerResponse]:
    """
    GET /photographers/followups
    """
    return await service.get_followups_due(db=db, skip=skip, limit=limit)


@router.get(
    "/status/{status}",
    response_model=List[PhotographerResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve by lead status",
    description="Fetches photographers filtered by their CRM lead lifecycle status."
)
async def get_photographers_by_status(
    status: LeadStatus,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    service: PhotographerService = Depends(get_photographer_service),
) -> List[PhotographerResponse]:
    """
    GET /photographers/status/{status}
    """
    return await service.get_photographers_by_status(db=db, status=status, skip=skip, limit=limit)


@router.patch(
    "/{id}/status",
    response_model=PhotographerResponse,
    status_code=status.HTTP_200_OK,
    summary="Update photographer status",
    description="Updates the lead status of a photographer. Enforces transition constraints."
)
async def update_status(
    id: uuid.UUID,
    payload: StatusUpdatePayload,
    allow_direct_customer: bool = False,
    db: AsyncSession = Depends(get_db),
    service: PhotographerService = Depends(get_photographer_service),
) -> PhotographerResponse:
    """
    PATCH /photographers/{id}/status
    """
    return await service.update_status(
        db=db,
        id=id,
        status=payload.status,
        allow_direct_customer=allow_direct_customer
    )


@router.patch(
    "/{id}/notes",
    response_model=PhotographerResponse,
    status_code=status.HTTP_200_OK,
    summary="Update internalnotes",
    description="Updates the internal notes for a photographer/lead."
)
async def update_notes(
    id: uuid.UUID,
    payload: NotesUpdatePayload,
    db: AsyncSession = Depends(get_db),
    service: PhotographerService = Depends(get_photographer_service),
) -> PhotographerResponse:
    """
    PATCH /photographers/{id}/notes
    """
    return await service.update_notes(db=db, id=id, internal_notes=payload.internal_notes)


# ==========================================
# STANDARD RETRIEVAL & MANAGEMENT
# ==========================================

@router.get(
    "/{id}",
    response_model=PhotographerResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve a photographer by ID",
    description="Retrieves details of a photographer matching the given UUID. Raises 404 if not found."
)
async def get_photographer(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: PhotographerService = Depends(get_photographer_service),
) -> PhotographerResponse:
    """
    GET /photographers/{id} Flow:
    FastAPI Route -> Injects deps -> Service.get_photographer_by_id -> Repository.get_by_id -> Returns model or raises 404.
    """
    return await service.get_photographer_by_id(db=db, id=id)


@router.put(
    "/{id}",
    response_model=PhotographerResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a photographer",
    description="Updates existing photographer details. Partially specified fields are ignored."
)
async def update_photographer(
    id: uuid.UUID,
    schema: PhotographerUpdate,
    db: AsyncSession = Depends(get_db),
    service: PhotographerService = Depends(get_photographer_service),
) -> PhotographerResponse:
    """
    PUT /photographers/{id} Flow:
    FastAPI Route -> Injects deps -> Service.update_photographer -> Repository.update -> Returns updated model.
    """
    return await service.update_photographer(db=db, id=id, schema=schema)


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a photographer",
    description="Deletes a photographer from the database. Raises 404 if not found."
)
async def delete_photographer(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: PhotographerService = Depends(get_photographer_service),
) -> None:
    """
    DELETE /photographers/{id} Flow:
    FastAPI Route -> Injects deps -> Service.delete_photographer -> Repository.delete -> Commits deletion.
    """
    await service.delete_photographer(db=db, id=id)

