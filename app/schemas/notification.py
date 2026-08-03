"""
app/schemas/notification.py

Pydantic schemas for NotificationLog.
"""

import uuid
from datetime import datetime
from pydantic import BaseModel, Field
from app.models.notification import NotificationType, NotificationChannel, NotificationStatus


class NotificationLogResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    notification_type: NotificationType
    channel: NotificationChannel
    recipient: str | None = None
    message_body: str
    status: NotificationStatus
    sent_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
