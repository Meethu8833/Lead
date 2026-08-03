"""
app/api/v1/endpoints/notifications.py

API endpoints for NotificationLog.
"""

import uuid
from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps import get_notification_service
from app.schemas.notification import NotificationLogResponse
from app.services.notification import NotificationService

router = APIRouter()


@router.get(
    "/orders/{order_id}/notifications",
    response_model=List[NotificationLogResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve notifications of an order"
)
async def get_notifications_by_order(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: NotificationService = Depends(get_notification_service),
) -> List[NotificationLogResponse]:
    return await service.get_by_order(db=db, order_id=order_id)


@router.get(
    "/notifications",
    response_model=List[NotificationLogResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve all notifications"
)
async def get_all_notifications(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    service: NotificationService = Depends(get_notification_service),
) -> List[NotificationLogResponse]:
    return await service.get_all_notifications(db=db, skip=skip, limit=limit)
