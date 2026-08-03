"""
app/api/v1/endpoints/attachments.py

This file defines the API routes (Endpoints) for the Attachment entity.
Under Clean Architecture, this resides in the API Layer (Interface Adapters).
"""

import uuid
from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_attachment_service
from app.schemas.attachment import AttachmentCreate, AttachmentResponse
from app.services.attachment import AttachmentService

router = APIRouter()


@router.post(
    "",
    response_model=AttachmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Attach a file to an entity",
    description="Registers an uploaded file's metadata for a specific order, item, invoice, or delivery. Enforces entity existence checks."
)
async def attach_file(
    schema: AttachmentCreate,
    db: AsyncSession = Depends(get_db),
    service: AttachmentService = Depends(get_attachment_service),
) -> AttachmentResponse:
    return await service.attach_file(db=db, schema=schema)


@router.get(
    "/{id}",
    response_model=AttachmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve attachment details",
    description="Retrieves metadata details of an attachment matching the given UUID."
)
async def get_attachment(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: AttachmentService = Depends(get_attachment_service),
) -> AttachmentResponse:
    return await service.get_attachment_by_id(db=db, id=id)


@router.get(
    "/entity/{entity_name}/{entity_id}",
    response_model=List[AttachmentResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve attachments for an entity",
    description="Fetches all uploaded attachments metadata associated with a specific business entity."
)
async def get_entity_attachments(
    entity_name: str,
    entity_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: AttachmentService = Depends(get_attachment_service),
) -> List[AttachmentResponse]:
    return await service.get_entity_attachments(db=db, entity_name=entity_name, entity_id=entity_id)


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an attachment metadata entry",
    description="Deletes attachment metadata from the system. (Actual file removal is handled separately)."
)
async def delete_attachment(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: AttachmentService = Depends(get_attachment_service),
) -> None:
    await service.delete_attachment(db=db, id=id)
