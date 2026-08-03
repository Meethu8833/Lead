"""
app/api/v1/endpoints/lead_activities.py

This file defines the API routes (Endpoints) for the Lead Activity & Notes module.
Under Clean Architecture, this file resides in the Interface Adapters layer.
It acts as the HTTP controller: parsing requests, delegating execution to the Service layer,
and returning structured JSON responses matching our Pydantic schemas.

Routing note: this router is mounted with an empty prefix in app/api/v1/router.py because
its paths straddle two resource roots — `/leads/{id}/...` for the lead-scoped collections
and `/lead-notes/{id}` for operations on a note by its own identity. That mirrors how
`order_items.py` handles the same `/orders/{id}/items` + `/order-items/{id}` split.

RBAC: reads require `leads:view`; all note mutations require `leads:update`. Notes are
commentary on a lead rather than a separately-owned resource, so they intentionally reuse
the lead permission set rather than introducing `lead-notes:*` permissions that no role
has been granted.
"""

import uuid
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_db,
    get_lead_activity_service,
    get_lead_note_service,
    RequirePermission,
)
from app.models.lead_activity import ActivityType
from app.schemas.lead_activity import (
    LeadNoteCreate,
    LeadNoteUpdate,
    LeadNoteResponse,
    LeadNoteListResponse,
    LeadActivityListResponse,
)
from app.services.lead_activity import LeadActivityService, LeadNoteService

router = APIRouter()


# =====================================================================
# LEAD NOTES
# =====================================================================

@router.get(
    "/leads/{id}/notes",
    response_model=LeadNoteListResponse,
    status_code=status.HTTP_200_OK,
    summary="List notes on a lead",
    description="Fetches a paginated list of manual notes attached to the lead, newest first. Raises 404 if the lead does not exist.",
    dependencies=[Depends(RequirePermission("leads:view"))],
)
async def get_lead_notes(
    id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    service: LeadNoteService = Depends(get_lead_note_service),
) -> LeadNoteListResponse:
    """
    GET /leads/{id}/notes Endpoint Flow:
    Validates the lead exists -> Service -> Repository -> paginated notes + total count.
    """
    items, total = await service.get_notes_by_lead(db=db, lead_id=id, skip=skip, limit=limit)
    return LeadNoteListResponse(items=items, total=total, skip=skip, limit=limit)


@router.post(
    "/leads/{id}/notes",
    response_model=LeadNoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a note to a lead",
    description="Creates a manual note on the lead and appends a matching NOTE entry to the lead's activity timeline. Raises 404 if the lead does not exist.",
    dependencies=[Depends(RequirePermission("leads:update"))],
)
async def create_lead_note(
    id: uuid.UUID,
    schema: LeadNoteCreate,
    db: AsyncSession = Depends(get_db),
    service: LeadNoteService = Depends(get_lead_note_service),
) -> LeadNoteResponse:
    """
    POST /leads/{id}/notes Endpoint Flow:
    Client JSON -> Validation -> Service (note + NOTE activity in one transaction) -> created note.
    """
    return await service.create_note(db=db, lead_id=id, schema=schema)


@router.put(
    "/lead-notes/{id}",
    response_model=LeadNoteResponse,
    status_code=status.HTTP_200_OK,
    summary="Edit a note",
    description="Updates the body of an existing note. Does not append a new timeline entry; the edit is captured by the automatic audit log. Raises 404 if the note does not exist or was deleted.",
    dependencies=[Depends(RequirePermission("leads:update"))],
)
async def update_lead_note(
    id: uuid.UUID,
    schema: LeadNoteUpdate,
    db: AsyncSession = Depends(get_db),
    service: LeadNoteService = Depends(get_lead_note_service),
) -> LeadNoteResponse:
    """
    PUT /lead-notes/{id} Endpoint Flow:
    Updates the note body after validating it is non-blank.
    """
    return await service.update_note(db=db, id=id, schema=schema)


@router.delete(
    "/lead-notes/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a note",
    description="Soft deletes a note. The NOTE entry already on the lead's timeline is preserved. Raises 404 if the note does not exist or was already deleted.",
    dependencies=[Depends(RequirePermission("leads:update"))],
)
async def delete_lead_note(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: LeadNoteService = Depends(get_lead_note_service),
) -> None:
    """
    DELETE /lead-notes/{id} Endpoint Flow:
    Soft deletes the note. Raises 404 if not found.
    """
    await service.delete_note(db=db, id=id)


# =====================================================================
# LEAD ACTIVITIES (TIMELINE)
# =====================================================================

@router.get(
    "/leads/{id}/activities",
    response_model=LeadActivityListResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a lead's activity timeline",
    description=(
        "Fetches the chronological timeline of everything that happened to the lead, newest first, "
        "with pagination. Optionally filtered to a single activity type. Raises 404 if the lead does not exist. "
        "Activities are append-only and cannot be created, edited, or deleted through the API."
    ),
    dependencies=[Depends(RequirePermission("leads:view"))],
)
async def get_lead_activities(
    id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    activity_type: ActivityType | None = Query(None, description="Filter the timeline to a single activity type"),
    db: AsyncSession = Depends(get_db),
    service: LeadActivityService = Depends(get_lead_activity_service),
) -> LeadActivityListResponse:
    """
    GET /leads/{id}/activities Endpoint Flow:
    Validates the lead exists -> Service -> Repository -> paginated newest-first timeline + total count.
    """
    items, total = await service.get_lead_timeline(
        db=db, lead_id=id, skip=skip, limit=limit, activity_type=activity_type
    )
    return LeadActivityListResponse(items=items, total=total, skip=skip, limit=limit)
