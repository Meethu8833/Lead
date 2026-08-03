"""
app/repositories/attachment.py

This file implements the AttachmentRepository.
Under Clean Architecture, this resides in the Interface Adapters layer.
"""

import uuid
from typing import Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.attachment import Attachment


class AttachmentRepository:
    """
    Attachment Repository.
    Handles storage metadata CRUD operations.
    """

    async def create(self, db: AsyncSession, attachment: Attachment) -> Attachment:
        db.add(attachment)
        await db.commit()
        await db.refresh(attachment)
        return attachment

    async def get_by_id(self, db: AsyncSession, id: uuid.UUID) -> Attachment | None:
        return await db.get(Attachment, id)

    async def get_all_by_entity(
        self, db: AsyncSession, entity_name: str, entity_id: uuid.UUID
    ) -> Sequence[Attachment]:
        query = (
            select(Attachment)
            .where(Attachment.entity_name == entity_name, Attachment.entity_id == entity_id)
            .order_by(Attachment.uploaded_at.desc())
        )
        result = await db.execute(query)
        return result.scalars().all()

    async def delete(self, db: AsyncSession, db_obj: Attachment) -> bool:
        await db.delete(db_obj)
        await db.commit()
        return True
