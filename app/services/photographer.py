"""
app/services/photographer.py

This file implements the PhotographerService.
Under Clean Architecture, this file belongs to the Application Business Rules (Use Cases) layer.
It contains the core business logic and orchestrates the data retrieval/persistence using the Repository.
"""

import uuid
from datetime import datetime, timezone
from typing import Sequence
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, NotFoundException, ConflictException
from app.models.photographer import Photographer, LeadStatus, LeadPriority
from app.schemas.photographer import PhotographerCreate, PhotographerUpdate
from app.repositories.photographer import PhotographerRepository


class PhotographerService:
    """
    Service layer containing business logic and orchestrating actions on Photographers.
    """

    def __init__(self, repository: PhotographerRepository | None = None) -> None:
        self.repository = repository or PhotographerRepository()

    async def create_photographer(self, db: AsyncSession, schema: PhotographerCreate) -> Photographer:
        """
        Creates a new photographer.
        Business Rules:
        - Phone number must be unique.
        - Name and studio name cannot be blank.
        - The initial lead status MUST be NEW.
        """
        if not schema.name.strip():
            raise BadRequestException("Photographer name cannot be empty.")
        if not schema.studio_name.strip():
            raise BadRequestException("Studio name cannot be empty.")
        
        # Business Rule: Unique phone number
        existing_phone = await self.repository.get_by_phone(db, phone=schema.phone)
        if existing_phone:
            raise BadRequestException(f"Photographer with phone number '{schema.phone}' already exists.")

        # Create model instance
        photographer = Photographer(
            name=schema.name,
            studio_name=schema.studio_name,
            phone=schema.phone,
            email=schema.email,
            city=schema.city,
            address=schema.address,
            category=schema.category,
            lead_source=schema.lead_source,
            lead_status=LeadStatus.NEW,  # Enforce status = NEW on creation
            priority=schema.priority or LeadPriority.MEDIUM,
            assigned_to=schema.assigned_to,
            last_contacted_at=schema.last_contacted_at,
            next_followup_at=schema.next_followup_at,
            last_contact_method=schema.last_contact_method,
            last_contact_note=schema.last_contact_note,
            instagram=schema.instagram,
            facebook=schema.facebook,
            website=schema.website,
            tags=schema.tags,
            internal_notes=schema.internal_notes,
            customer_since=None,  # Not a customer on creation
            is_active=True,
        )

        return await self.repository.create(db, photographer)

    async def get_photographer_by_id(self, db: AsyncSession, id: uuid.UUID) -> Photographer:
        """
        Retrieves a photographer by ID.
        Raises NotFoundException if the photographer does not exist.
        """
        photographer = await self.repository.get_by_id(db, id)
        if not photographer:
            raise NotFoundException(f"Photographer with ID '{id}' was not found.")
        return photographer

    async def get_all_photographers(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> Sequence[Photographer]:
        """
        Retrieves a paginated list of photographers.
        """
        return await self.repository.get_all(db, skip=skip, limit=limit)

    async def update_photographer(
        self, db: AsyncSession, id: uuid.UUID, schema: PhotographerUpdate, allow_direct_customer: bool = False
    ) -> Photographer:
        """
        Updates an existing photographer.
        Business Rules:
        - Validate version for optimistic locking.
        - If phone is being updated, it must remain unique.
        - Prevent changing status directly from NEW to CUSTOMER unless explicitly allowed.
        - Automatically update last_contacted_at if status changes to CONTACTED.
        - Automatically update customer_since if status changes to CUSTOMER.
        """
        photographer = await self.repository.get_by_id(db, id)
        if not photographer:
            raise NotFoundException(f"Photographer with ID '{id}' was not found.")

        # Optimistic locking check
        if schema.version is not None and photographer.version != schema.version:
            raise ConflictException("Photographer was modified by another process. Please reload.")

        update_data = schema.model_dump(exclude_unset=True)
        update_data.pop("version", None)

        # Business Rule: Unique phone number
        new_phone = update_data.get("phone")
        if new_phone and new_phone != photographer.phone:
            existing_phone = await self.repository.get_by_phone(db, phone=new_phone)
            if existing_phone:
                raise BadRequestException(f"Photographer with phone number '{new_phone}' already exists.")

        # Business Rule: Enforce lead status transitions
        new_status = update_data.get("lead_status")
        if new_status and new_status != photographer.lead_status:
            if photographer.lead_status == LeadStatus.NEW and new_status == LeadStatus.CUSTOMER:
                if not allow_direct_customer:
                    raise BadRequestException("Changing status directly from NEW to CUSTOMER is blocked unless explicitly allowed.")
            
            # Automatically update last_contacted_at if status changes to CONTACTED
            if new_status == LeadStatus.CONTACTED:
                update_data["last_contacted_at"] = datetime.now(timezone.utc)
            # Automatically update customer_since if status changes to CUSTOMER
            elif new_status == LeadStatus.CUSTOMER:
                update_data["customer_since"] = datetime.now(timezone.utc)

        return await self.repository.update(db, db_obj=photographer, update_data=update_data)

    async def delete_photographer(self, db: AsyncSession, id: uuid.UUID) -> None:
        """
        Deletes an existing photographer and cascades soft deletion to orders and items.
        Raises NotFoundException if the photographer does not exist.
        """
        photographer = await self.repository.get_by_id(db, id)
        if not photographer:
            raise NotFoundException(f"Photographer with ID '{id}' was not found.")
        
        # Cascade soft delete to all orders and their items
        from app.repositories.order import OrderRepository
        order_repo = OrderRepository()
        orders = await order_repo.get_by_photographer(db, photographer_id=id, limit=1000)
        for order in orders:
            for item in order.items:
                item.is_deleted = True
                item.deleted_at = datetime.now(timezone.utc)
                db.add(item)
            order.is_deleted = True
            order.deleted_at = datetime.now(timezone.utc)
            db.add(order)

        await self.repository.delete(db, db_obj=photographer)

    # ==========================
    # CRM SPECIFIC SERVICES
    # ==========================
    async def get_photographers_by_status(
        self, db: AsyncSession, status: LeadStatus, skip: int = 0, limit: int = 100
    ) -> Sequence[Photographer]:
        """
        Retrieves a list of photographers filtered by lead status.
        """
        return await self.repository.get_by_status(db, status=status, skip=skip, limit=limit)

    async def get_followups_due(
        self, db: AsyncSession, skip: int = 0, limit: int = 100
    ) -> Sequence[Photographer]:
        """
        Retrieves a list of photographers whose followups are due/overdue.
        """
        return await self.repository.get_followups_due(db, skip=skip, limit=limit)

    async def search_photographers(
        self,
        db: AsyncSession,
        name: str | None = None,
        phone: str | None = None,
        city: str | None = None,
        studio_name: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[Photographer]:
        """
        Searches photographers using filters on name, phone, city, or studio_name.
        """
        return await self.repository.search(
            db, name=name, phone=phone, city=city, studio_name=studio_name, skip=skip, limit=limit
        )

    async def update_status(
        self, db: AsyncSession, id: uuid.UUID, status: LeadStatus, allow_direct_customer: bool = False
    ) -> Photographer:
        """
        Updates the lead status of a photographer.
        """
        update_schema = PhotographerUpdate(lead_status=status)
        return await self.update_photographer(
            db=db, id=id, schema=update_schema, allow_direct_customer=allow_direct_customer
        )

    async def update_notes(self, db: AsyncSession, id: uuid.UUID, internal_notes: str) -> Photographer:
        """
        Updates the internal notes of a photographer.
        """
        update_schema = PhotographerUpdate(internal_notes=internal_notes)
        return await self.update_photographer(db=db, id=id, schema=update_schema)

