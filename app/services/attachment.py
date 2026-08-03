"""
app/services/attachment.py

This file implements the AttachmentService.
Under Clean Architecture, this resides in the Application Business Rules (Use Cases) layer.
"""

import uuid
from typing import Sequence
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, BadRequestException
from app.models.attachment import Attachment
from app.schemas.attachment import AttachmentCreate
from app.repositories.attachment import AttachmentRepository

# Repositories for existence checking
from app.repositories.order import OrderRepository
from app.repositories.order_item import OrderItemRepository
from app.repositories.invoice import InvoiceRepository
from app.repositories.delivery import DeliveryRepository
from app.core.context import audit_context


class AttachmentService:
    """
    Service layer containing business logic and orchestrating actions on file attachments.
    """

    def __init__(
        self,
        attachment_repository: AttachmentRepository | None = None,
        order_repository: OrderRepository | None = None,
        order_item_repository: OrderItemRepository | None = None,
        invoice_repository: InvoiceRepository | None = None,
        delivery_repository: DeliveryRepository | None = None,
    ) -> None:
        self.attachment_repository = attachment_repository or AttachmentRepository()
        self.order_repository = order_repository or OrderRepository()
        self.order_item_repository = order_item_repository or OrderItemRepository()
        self.invoice_repository = invoice_repository or InvoiceRepository()
        self.delivery_repository = delivery_repository or DeliveryRepository()

    async def attach_file(self, db: AsyncSession, schema: AttachmentCreate) -> Attachment:
        """
        Validates target entity existence and registers the attachment details.
        """
        # Enforce existence constraints to prevent orphan attachment records
        entity_name = schema.entity_name
        entity_id = schema.entity_id

        if entity_name == "Order":
            order = await self.order_repository.get_by_id(db, entity_id)
            if not order:
                raise NotFoundException(f"Order with ID '{entity_id}' was not found.")
        elif entity_name == "OrderItem":
            item = await self.order_item_repository.get_by_id(db, entity_id)
            if not item:
                raise NotFoundException(f"OrderItem with ID '{entity_id}' was not found.")
        elif entity_name == "Invoice":
            invoice = await self.invoice_repository.get_by_id(db, entity_id)
            if not invoice:
                raise NotFoundException(f"Invoice with ID '{entity_id}' was not found.")
        elif entity_name == "Delivery":
            delivery = await self.delivery_repository.get_by_id(db, entity_id)
            if not delivery:
                raise NotFoundException(f"Delivery with ID '{entity_id}' was not found.")
        else:
            raise BadRequestException(f"Unsupported attachment entity: '{entity_name}'.")

        ctx = audit_context.get()
        uploaded_by = ctx.get("user_id") if ctx else "SYSTEM"

        attachment = Attachment(
            entity_name=entity_name,
            entity_id=entity_id,
            file_name=schema.file_name,
            mime_type=schema.mime_type,
            storage_path=schema.storage_path,
            uploaded_by=uploaded_by,
        )

        return await self.attachment_repository.create(db, attachment)

    async def get_attachment_by_id(self, db: AsyncSession, id: uuid.UUID) -> Attachment:
        """
        Retrieves attachment details by ID.
        """
        attachment = await self.attachment_repository.get_by_id(db, id)
        if not attachment:
            raise NotFoundException(f"Attachment with ID '{id}' was not found.")
        return attachment

    async def get_entity_attachments(
        self, db: AsyncSession, entity_name: str, entity_id: uuid.UUID
    ) -> Sequence[Attachment]:
        """
        Retrieves all attachments for a specific business entity.
        """
        # Validate entity name
        allowed = {"Order", "OrderItem", "Invoice", "Delivery"}
        if entity_name not in allowed:
            raise BadRequestException(f"Unsupported entity name: '{entity_name}'.")

        return await self.attachment_repository.get_all_by_entity(db, entity_name=entity_name, entity_id=entity_id)

    async def delete_attachment(self, db: AsyncSession, id: uuid.UUID) -> None:
        """
        Deletes attachment metadata.
        """
        attachment = await self.attachment_repository.get_by_id(db, id)
        if not attachment:
            raise NotFoundException(f"Attachment with ID '{id}' was not found.")
        await self.attachment_repository.delete(db, db_obj=attachment)
