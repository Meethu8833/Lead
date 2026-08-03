"""
app/services/notification.py

Service layer for NotificationLog operations.
"""

import uuid
from datetime import datetime, timezone
from typing import Sequence
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.notification import NotificationLog, NotificationType, NotificationChannel, NotificationStatus
from app.repositories.notification import NotificationRepository


class NotificationService:
    def __init__(self, notification_repository: NotificationRepository | None = None) -> None:
        self.notification_repository = notification_repository or NotificationRepository()

    async def log_notification(
        self,
        db: AsyncSession,
        order_id: uuid.UUID,
        notification_type: NotificationType,
        channel: NotificationChannel,
        recipient: str | None,
        message_body: str,
        commit: bool = True
    ) -> NotificationLog:
        """
        Creates a notification log entry. Sets sending status depending on the channel.
        For SYSTEM, EMAIL, and SMS: Mock sending by marking as SENT immediately.
        For WHATSAPP: Mark as PENDING since it is not yet integrated.
        """
        status = NotificationStatus.PENDING
        sent_at = None

        if channel in [NotificationChannel.SYSTEM, NotificationChannel.EMAIL, NotificationChannel.SMS]:
            # Mock successful sending
            status = NotificationStatus.SENT
            sent_at = datetime.now(timezone.utc)
        elif channel == NotificationChannel.WHATSAPP:
            # Not integrated yet - leave as PENDING
            status = NotificationStatus.PENDING

        notification = NotificationLog(
            order_id=order_id,
            notification_type=notification_type,
            channel=channel,
            recipient=recipient,
            message_body=message_body,
            status=status,
            sent_at=sent_at
        )

        return await self.notification_repository.create(db, notification, commit=commit)

    async def get_by_order(self, db: AsyncSession, order_id: uuid.UUID) -> Sequence[NotificationLog]:
        return await self.notification_repository.get_by_order_id(db, order_id)

    async def get_all_notifications(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> Sequence[NotificationLog]:
        return await self.notification_repository.get_all(db, skip=skip, limit=limit)
