"""
app/services/lead.py

This file implements the LeadService.
Under Clean Architecture, this file belongs to the Application Business Rules (Use Cases) layer.
It contains the core business logic and orchestrates the data retrieval/persistence using the Repository.
"""

import uuid
from datetime import datetime
from typing import Sequence
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, NotFoundException, ConflictException
from app.models.lead import Lead, LeadStatus, LeadSource
from app.schemas.lead import LeadCreate, LeadUpdate
from app.repositories.lead import LeadRepository
from app.services.lead_activity import LeadActivityService


def _serialize(value) -> object:
    """
    Renders a Lead attribute into something JSON-storable for an activity's metadata.
    Enums become their value, UUIDs/datetimes become strings, everything else passes through.
    """
    import uuid as _uuid
    from datetime import datetime as _datetime, date as _date
    from decimal import Decimal as _Decimal
    import enum as _enum

    if isinstance(value, _enum.Enum):
        return value.value
    if isinstance(value, _uuid.UUID):
        return str(value)
    if isinstance(value, (_datetime, _date)):
        return value.isoformat()
    if isinstance(value, _Decimal):
        return float(value)
    return value


class LeadService:
    """
    Service layer containing business logic and orchestrating actions on Leads.

    Beyond CRUD, this service is responsible for emitting the automatic timeline entries
    for the Lead Activity module (created / updated / status changed / converted / deleted).
    Activities are written through LeadActivityService so the timeline's structure stays in
    one place; see app/services/lead_activity.py.
    """

    def __init__(
        self,
        repository: LeadRepository | None = None,
        activity_service: LeadActivityService | None = None,
    ) -> None:
        self.repository = repository or LeadRepository()
        self.activity_service = activity_service or LeadActivityService()

    async def create_lead(self, db: AsyncSession, schema: LeadCreate) -> Lead:
        """
        Creates a new lead.
        Business Rules:
        - Business name cannot be blank.
        - Phone number must be unique.
        - New leads always start at status NEW, regardless of what was requested.
        - A CREATED activity is appended to the lead's timeline, atomically with the lead.
        """
        if not schema.business_name.strip():
            raise BadRequestException("Business name cannot be empty.")

        existing_phone = await self.repository.get_by_phone(db, phone=schema.phone)
        if existing_phone:
            raise BadRequestException(f"Lead with phone number '{schema.phone}' already exists.")

        lead = Lead(
            business_name=schema.business_name,
            contact_person=schema.contact_person,
            phone=schema.phone,
            whatsapp=schema.whatsapp,
            email=schema.email,
            instagram=schema.instagram,
            facebook=schema.facebook,
            website=schema.website,
            address=schema.address,
            city=schema.city,
            district=schema.district,
            state=schema.state,
            country=schema.country,
            latitude=schema.latitude,
            longitude=schema.longitude,
            source=schema.source or LeadSource.MANUAL,
            status=LeadStatus.NEW,  # Enforce status = NEW on creation
            assigned_employee_id=schema.assigned_employee_id,
            remarks=schema.remarks,
            is_converted=False,
        )

        lead = await self.repository.create(db, lead)
        await self.activity_service.log_created(db, lead)
        return lead

    async def get_lead_by_id(self, db: AsyncSession, id: uuid.UUID) -> Lead:
        """
        Retrieves a lead by ID.
        Raises NotFoundException if the lead does not exist.
        """
        lead = await self.repository.get_by_id(db, id)
        if not lead:
            raise NotFoundException(f"Lead with ID '{id}' was not found.")
        return lead

    async def get_all_leads(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        status: LeadStatus | None = None,
        source: LeadSource | None = None,
        district: str | None = None,
        city: str | None = None,
        assigned_employee_id: uuid.UUID | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        search: str | None = None,
    ) -> tuple[Sequence[Lead], int]:
        """
        Retrieves a paginated, optionally filtered and/or searched list of leads.
        Filters: status, source, district, city, assigned employee, created date range.
        Search: business_name, contact_person, phone, whatsapp, email (case-insensitive partial match).
        """
        return await self.repository.get_all(
            db,
            skip=skip,
            limit=limit,
            status=status,
            source=source,
            district=district,
            city=city,
            assigned_employee_id=assigned_employee_id,
            created_from=created_from,
            created_to=created_to,
            search=search,
        )

    async def update_lead(self, db: AsyncSession, id: uuid.UUID, schema: LeadUpdate) -> Lead:
        """
        Updates an existing lead.
        Business Rules:
        - Validate version for optimistic locking.
        - If phone is being updated, it must remain unique.
        - Emits timeline activities for what actually changed: a generic UPDATED entry,
          plus a dedicated STATUS_CHANGED entry on a status transition and a CONVERTED
          entry when the lead becomes a customer.
        """
        lead = await self.repository.get_by_id(db, id)
        if not lead:
            raise NotFoundException(f"Lead with ID '{id}' was not found.")

        if schema.version is not None and lead.version != schema.version:
            raise ConflictException("Lead was modified by another process. Please reload.")

        update_data = schema.model_dump(exclude_unset=True)
        update_data.pop("version", None)

        new_phone = update_data.get("phone")
        if new_phone and new_phone != lead.phone:
            existing_phone = await self.repository.get_by_phone(db, phone=new_phone)
            if existing_phone:
                raise BadRequestException(f"Lead with phone number '{new_phone}' already exists.")

        # Snapshot the fields being written *before* the repository mutates the instance,
        # so the activity can report a real old → new diff. Fields whose submitted value
        # equals the current value are dropped: a PUT that re-sends unchanged data is not
        # a change and should not appear on the timeline.
        changes: dict[str, dict] = {}
        for field, new_value in update_data.items():
            if not hasattr(lead, field):
                continue
            old_value = getattr(lead, field)
            if old_value != new_value:
                changes[field] = {"old": _serialize(old_value), "new": _serialize(new_value)}

        old_status = lead.status
        was_converted = lead.is_converted

        lead = await self.repository.update(db, db_obj=lead, update_data=update_data)

        # Timeline entries, emitted after the write so they only ever describe a change
        # that actually landed.
        await self.activity_service.log_updated(db, lead, changes)

        if "status" in changes:
            await self.activity_service.log_status_changed(db, lead, old_status, lead.status)

        # "Converted" fires on the transition, not the state, so re-saving an already
        # converted lead does not append a duplicate CONVERTED entry. Either the explicit
        # is_converted flag flipping to True, or status arriving at CUSTOMER, counts.
        became_converted = (
            (not was_converted and lead.is_converted)
            or (old_status != LeadStatus.CUSTOMER and lead.status == LeadStatus.CUSTOMER)
        )
        if became_converted:
            await self.activity_service.log_converted(db, lead)

        return lead

    async def delete_lead(self, db: AsyncSession, id: uuid.UUID) -> None:
        """
        Soft deletes an existing lead.
        Raises NotFoundException if the lead does not exist.

        The DELETED activity is written *before* the soft delete, because the timeline
        read path (`LeadActivityService.get_lead_timeline`) resolves the parent lead
        through the default repository, which filters out soft-deleted rows. Writing
        first keeps the ordering of the two statements irrelevant to correctness, and the
        entry remains recoverable through AdminLeadRepository-backed reads.
        """
        lead = await self.repository.get_by_id(db, id)
        if not lead:
            raise NotFoundException(f"Lead with ID '{id}' was not found.")

        await self.activity_service.log_deleted(db, lead)
        await self.repository.delete(db, db_obj=lead)
