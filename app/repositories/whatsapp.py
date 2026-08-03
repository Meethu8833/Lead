"""
app/repositories/whatsapp.py

This file implements the repositories for the WhatsApp Campaign Management module:
WhatsAppTemplateRepository, WhatsAppCampaignRepository and CampaignRecipientRepository.
Under Clean Architecture, this file belongs to the Interface Adapters layer. It encapsulates
SQLAlchemy access and keeps the service layer free of query construction.

All three follow the house conventions established in `app/repositories/lead.py` and
`app/repositories/lead_activity.py`:
- `create`/`update`/`delete` take `commit: bool = True` so a service can batch several
  writes into one transaction.
- List queries return a `(rows, total)` tuple so the API layer can build pagination
  metadata without a second round trip.
- Soft-deleted rows are excluded by default, with an `Admin*` subclass that includes them.
"""

import uuid
from typing import Sequence
from datetime import datetime, timezone
from sqlalchemy import select, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead
from app.models.whatsapp import (
    WhatsAppTemplate,
    WhatsAppCampaign,
    CampaignRecipient,
    TemplateCategory,
    CampaignStatus,
    MessageStatus,
)


class WhatsAppTemplateRepository:
    """
    WhatsAppTemplate Repository.
    Handles CRUD and querying on the whatsapp_templates table.
    """

    def __init__(self, include_deleted: bool = False) -> None:
        self.include_deleted = include_deleted

    async def create(
        self, db: AsyncSession, template: WhatsAppTemplate, commit: bool = True
    ) -> WhatsAppTemplate:
        """
        Persists a new template.
        """
        db.add(template)
        if commit:
            await db.commit()
            await db.refresh(template)
        else:
            await db.flush()
        return template

    async def get_by_id(
        self, db: AsyncSession, id: uuid.UUID, include_deleted: bool | None = None
    ) -> WhatsAppTemplate | None:
        """
        Fetches a single template by its UUID.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(WhatsAppTemplate).where(WhatsAppTemplate.id == id)
        if not inc:
            query = query.where(WhatsAppTemplate.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().first()

    async def get_by_name(
        self, db: AsyncSession, name: str, include_deleted: bool | None = None
    ) -> WhatsAppTemplate | None:
        """
        Fetches a template by its name. Used to enforce name uniqueness at the service
        layer before the partial unique index would raise.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(WhatsAppTemplate).where(func.lower(WhatsAppTemplate.name) == name.strip().lower())
        if not inc:
            query = query.where(WhatsAppTemplate.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().first()

    def _apply_filters(
        self,
        query,
        category: TemplateCategory | None = None,
        language: str | None = None,
        is_active: bool | None = None,
        search: str | None = None,
        include_deleted: bool = False,
    ):
        """
        Applies the shared filter/search predicate set to a base select() query.
        """
        filters = []
        if category:
            filters.append(WhatsAppTemplate.category == category)
        if language:
            filters.append(WhatsAppTemplate.language == language.strip())
        if is_active is not None:
            filters.append(WhatsAppTemplate.is_active == is_active)
        if search:
            keyword = f"%{search.strip()}%"
            filters.append(
                or_(
                    WhatsAppTemplate.name.ilike(keyword),
                    WhatsAppTemplate.message_body.ilike(keyword),
                )
            )
        if not include_deleted:
            filters.append(WhatsAppTemplate.is_deleted == False)

        if filters:
            query = query.where(and_(*filters))
        return query

    async def get_all(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        category: TemplateCategory | None = None,
        language: str | None = None,
        is_active: bool | None = None,
        search: str | None = None,
        include_deleted: bool | None = None,
    ) -> tuple[Sequence[WhatsAppTemplate], int]:
        """
        Fetches a paginated, filtered list of templates plus the total count of matching
        rows (ignoring skip/limit) for pagination metadata.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted

        base_query = self._apply_filters(
            select(WhatsAppTemplate),
            category=category, language=language, is_active=is_active,
            search=search, include_deleted=inc,
        )
        count_query = self._apply_filters(
            select(func.count()).select_from(WhatsAppTemplate),
            category=category, language=language, is_active=is_active,
            search=search, include_deleted=inc,
        )

        total = (await db.execute(count_query)).scalar_one()
        query = (
            base_query
            .order_by(WhatsAppTemplate.created_at.desc(), WhatsAppTemplate.id.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(query)
        return result.scalars().all(), total

    async def update(
        self, db: AsyncSession, db_obj: WhatsAppTemplate, update_data: dict, commit: bool = True
    ) -> WhatsAppTemplate:
        """
        Updates a template's attributes.
        """
        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)

        db.add(db_obj)
        if commit:
            await db.commit()
            await db.refresh(db_obj)
        else:
            await db.flush()
        return db_obj

    async def delete(self, db: AsyncSession, db_obj: WhatsAppTemplate, commit: bool = True) -> bool:
        """
        Soft deletes a template.
        """
        db_obj.is_deleted = True
        db_obj.deleted_at = datetime.now(timezone.utc)
        db.add(db_obj)
        if commit:
            await db.commit()
        else:
            await db.flush()
        return True

    async def count_campaigns_using(self, db: AsyncSession, template_id: uuid.UUID) -> int:
        """
        Counts live campaigns referencing this template.

        The service uses this to refuse deletion of a template that active campaigns still
        depend on, producing a clear 400 instead of letting the ON DELETE RESTRICT foreign
        key surface as an opaque 500 later.
        """
        query = (
            select(func.count())
            .select_from(WhatsAppCampaign)
            .where(
                WhatsAppCampaign.template_id == template_id,
                WhatsAppCampaign.is_deleted == False,
            )
        )
        return (await db.execute(query)).scalar_one()


class AdminWhatsAppTemplateRepository(WhatsAppTemplateRepository):
    """
    Template repository that includes soft-deleted rows by default.
    Mirrors AdminLeadRepository in app/repositories/lead.py.
    """
    def __init__(self) -> None:
        super().__init__(include_deleted=True)


class WhatsAppCampaignRepository:
    """
    WhatsAppCampaign Repository.
    Handles CRUD and querying on the whatsapp_campaigns table.
    """

    def __init__(self, include_deleted: bool = False) -> None:
        self.include_deleted = include_deleted

    async def create(
        self, db: AsyncSession, campaign: WhatsAppCampaign, commit: bool = True
    ) -> WhatsAppCampaign:
        """
        Persists a new campaign.
        """
        db.add(campaign)
        if commit:
            await db.commit()
            await db.refresh(campaign)
        else:
            await db.flush()
        return campaign

    async def get_by_id(
        self, db: AsyncSession, id: uuid.UUID, include_deleted: bool | None = None
    ) -> WhatsAppCampaign | None:
        """
        Fetches a single campaign by its UUID.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(WhatsAppCampaign).where(WhatsAppCampaign.id == id)
        if not inc:
            query = query.where(WhatsAppCampaign.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().first()

    def _apply_filters(
        self,
        query,
        status: CampaignStatus | None = None,
        template_id: uuid.UUID | None = None,
        created_by: uuid.UUID | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        search: str | None = None,
        include_deleted: bool = False,
    ):
        """
        Applies the shared filter/search predicate set to a base select() query.
        """
        filters = []
        if status:
            filters.append(WhatsAppCampaign.status == status)
        if template_id:
            filters.append(WhatsAppCampaign.template_id == template_id)
        if created_by:
            filters.append(WhatsAppCampaign.created_by == created_by)
        if created_from:
            filters.append(WhatsAppCampaign.created_at >= created_from)
        if created_to:
            filters.append(WhatsAppCampaign.created_at <= created_to)
        if search:
            keyword = f"%{search.strip()}%"
            filters.append(
                or_(
                    WhatsAppCampaign.name.ilike(keyword),
                    WhatsAppCampaign.description.ilike(keyword),
                )
            )
        if not include_deleted:
            filters.append(WhatsAppCampaign.is_deleted == False)

        if filters:
            query = query.where(and_(*filters))
        return query

    async def get_all(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        status: CampaignStatus | None = None,
        template_id: uuid.UUID | None = None,
        created_by: uuid.UUID | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        search: str | None = None,
        include_deleted: bool | None = None,
    ) -> tuple[Sequence[WhatsAppCampaign], int]:
        """
        Fetches a paginated, filtered list of campaigns plus the total count of matching
        rows (ignoring skip/limit) for pagination metadata.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted

        base_query = self._apply_filters(
            select(WhatsAppCampaign),
            status=status, template_id=template_id, created_by=created_by,
            created_from=created_from, created_to=created_to, search=search,
            include_deleted=inc,
        )
        count_query = self._apply_filters(
            select(func.count()).select_from(WhatsAppCampaign),
            status=status, template_id=template_id, created_by=created_by,
            created_from=created_from, created_to=created_to, search=search,
            include_deleted=inc,
        )

        total = (await db.execute(count_query)).scalar_one()
        query = (
            base_query
            .order_by(WhatsAppCampaign.created_at.desc(), WhatsAppCampaign.id.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(query)
        return result.scalars().all(), total

    async def get_due_for_dispatch(
        self, db: AsyncSession, as_of: datetime, limit: int = 100
    ) -> Sequence[WhatsAppCampaign]:
        """
        Fetches SCHEDULED campaigns whose `scheduled_at` has arrived, oldest schedule first.

        This is the query a scheduler/worker would poll. No such worker is wired up in this
        phase — scheduling is recorded and exposed, and a campaign is dispatched by an
        explicit call to the start endpoint — but the query lives here so adding a poller
        later requires no repository change.
        """
        query = (
            select(WhatsAppCampaign)
            .where(
                WhatsAppCampaign.status == CampaignStatus.SCHEDULED,
                WhatsAppCampaign.scheduled_at != None,
                WhatsAppCampaign.scheduled_at <= as_of,
                WhatsAppCampaign.is_deleted == False,
            )
            .order_by(WhatsAppCampaign.scheduled_at.asc())
            .limit(limit)
        )
        result = await db.execute(query)
        return result.scalars().all()

    async def update(
        self, db: AsyncSession, db_obj: WhatsAppCampaign, update_data: dict, commit: bool = True
    ) -> WhatsAppCampaign:
        """
        Updates a campaign's attributes.
        """
        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)

        db.add(db_obj)
        if commit:
            await db.commit()
            await db.refresh(db_obj)
        else:
            await db.flush()
        return db_obj

    async def delete(self, db: AsyncSession, db_obj: WhatsAppCampaign, commit: bool = True) -> bool:
        """
        Soft deletes a campaign.
        """
        db_obj.is_deleted = True
        db_obj.deleted_at = datetime.now(timezone.utc)
        db.add(db_obj)
        if commit:
            await db.commit()
        else:
            await db.flush()
        return True


class AdminWhatsAppCampaignRepository(WhatsAppCampaignRepository):
    """
    Campaign repository that includes soft-deleted rows by default.
    """
    def __init__(self) -> None:
        super().__init__(include_deleted=True)


class CampaignRecipientRepository:
    """
    CampaignRecipient Repository.
    Handles CRUD, bulk enrolment and aggregate queries on the campaign_recipients table.

    There is no soft delete here: a recipient row is part of a campaign's delivery record
    and is removed only when its parent campaign or lead is genuinely hard-deleted (via
    ON DELETE CASCADE). Removing a recipient from a not-yet-started campaign is therefore
    a real delete, exposed as `delete`.
    """

    async def create(
        self, db: AsyncSession, recipient: CampaignRecipient, commit: bool = True
    ) -> CampaignRecipient:
        """
        Persists a single recipient row.
        """
        db.add(recipient)
        if commit:
            await db.commit()
            await db.refresh(recipient)
        else:
            await db.flush()
        return recipient

    async def bulk_create(
        self, db: AsyncSession, recipients: list[CampaignRecipient], commit: bool = True
    ) -> list[CampaignRecipient]:
        """
        Persists many recipient rows in one flush.

        Enrolling a campaign's audience is inherently a bulk operation, and adding rows one
        commit at a time would leave a partially-enrolled campaign behind on any failure.
        """
        if not recipients:
            return []
        db.add_all(recipients)
        if commit:
            await db.commit()
        else:
            await db.flush()
        return recipients

    async def get_by_id(self, db: AsyncSession, id: uuid.UUID) -> CampaignRecipient | None:
        """
        Fetches a single recipient row by its UUID.
        """
        result = await db.execute(select(CampaignRecipient).where(CampaignRecipient.id == id))
        return result.scalars().first()

    async def get_by_campaign_and_lead(
        self, db: AsyncSession, campaign_id: uuid.UUID, lead_id: uuid.UUID
    ) -> CampaignRecipient | None:
        """
        Fetches the recipient row joining one campaign to one lead, if it exists.
        Backs the de-duplication rule behind the (campaign_id, lead_id) unique constraint.
        """
        query = select(CampaignRecipient).where(
            CampaignRecipient.campaign_id == campaign_id,
            CampaignRecipient.lead_id == lead_id,
        )
        result = await db.execute(query)
        return result.scalars().first()

    async def get_by_provider_message_id(
        self, db: AsyncSession, provider_message_id: str
    ) -> CampaignRecipient | None:
        """
        Fetches a recipient row by the provider's opaque message identifier.
        This is the lookup an inbound status/reply webhook uses.
        """
        query = select(CampaignRecipient).where(
            CampaignRecipient.provider_message_id == provider_message_id
        )
        result = await db.execute(query)
        return result.scalars().first()

    async def get_latest_for_phone(
        self, db: AsyncSession, phone: str
    ) -> CampaignRecipient | None:
        """
        Fetches the most recently dispatched recipient row for a phone number.

        Reply webhooks from several providers identify the inbound message only by the
        sender's number, with no reference to the outbound message it answers. Attributing
        such a reply to that number's most recent dispatch is the best available
        correlation, and matches how a human would read the conversation.

        Only rows that were actually dispatched are considered (`sent_at` is not null), so
        an untouched PENDING enrolment in some unrelated draft campaign can never absorb
        a reply.
        """
        query = (
            select(CampaignRecipient)
            .where(
                CampaignRecipient.phone == phone,
                CampaignRecipient.sent_at != None,
            )
            .order_by(CampaignRecipient.sent_at.desc(), CampaignRecipient.id.desc())
            .limit(1)
        )
        result = await db.execute(query)
        return result.scalars().first()

    async def get_by_campaign(
        self,
        db: AsyncSession,
        campaign_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
        message_status: MessageStatus | None = None,
    ) -> tuple[Sequence[CampaignRecipient], int]:
        """
        Fetches a campaign's recipients, oldest enrolment first, plus the total count of
        matching rows (ignoring skip/limit).

        Ordering is ascending with an `id` tiebreaker: bulk enrolment writes many rows
        inside one transaction that share an identical `created_at` (Postgres `now()` is
        fixed per transaction), so without the deterministic secondary sort rows could
        shuffle between pages and be duplicated or skipped.
        """
        filters = [CampaignRecipient.campaign_id == campaign_id]
        if message_status:
            filters.append(CampaignRecipient.message_status == message_status)

        count_query = select(func.count()).select_from(CampaignRecipient).where(*filters)
        total = (await db.execute(count_query)).scalar_one()

        query = (
            select(CampaignRecipient)
            .where(*filters)
            .order_by(CampaignRecipient.created_at.asc(), CampaignRecipient.id.asc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(query)
        return result.scalars().all(), total

    async def get_all_for_campaign(
        self, db: AsyncSession, campaign_id: uuid.UUID, message_status: MessageStatus | None = None
    ) -> Sequence[CampaignRecipient]:
        """
        Fetches every recipient row of a campaign, unpaginated.
        Used by the dispatch loop, which must iterate the whole audience.
        """
        filters = [CampaignRecipient.campaign_id == campaign_id]
        if message_status:
            filters.append(CampaignRecipient.message_status == message_status)

        query = (
            select(CampaignRecipient)
            .where(*filters)
            .order_by(CampaignRecipient.created_at.asc(), CampaignRecipient.id.asc())
        )
        result = await db.execute(query)
        return result.scalars().all()

    async def status_counts(self, db: AsyncSession, campaign_id: uuid.UUID) -> dict[MessageStatus, int]:
        """
        Returns the number of recipients in each message status for one campaign, computed
        by the database in a single grouped query.

        This is the authoritative source for campaign statistics; the `total_*` columns on
        the campaign row are a denormalized cache of it (see the model docstring).
        """
        query = (
            select(CampaignRecipient.message_status, func.count())
            .where(CampaignRecipient.campaign_id == campaign_id)
            .group_by(CampaignRecipient.message_status)
        )
        result = await db.execute(query)
        return {status: count for status, count in result.all()}

    async def get_eligible_leads(
        self,
        db: AsyncSession,
        lead_ids: Sequence[uuid.UUID] | None = None,
    ) -> Sequence[Lead]:
        """
        Fetches the live, non-converted leads that may be enrolled as recipients.

        Filtering happens here rather than in the service so the "who can be messaged"
        predicate is expressed as one SQL query instead of N per-lead lookups. Soft-deleted
        leads are excluded; leads with no phone number cannot exist (the column is NOT NULL).
        """
        query = select(Lead).where(Lead.is_deleted == False)
        if lead_ids is not None:
            if not lead_ids:
                return []
            query = query.where(Lead.id.in_(list(lead_ids)))
        result = await db.execute(query)
        return result.scalars().all()

    async def update(
        self, db: AsyncSession, db_obj: CampaignRecipient, update_data: dict, commit: bool = True
    ) -> CampaignRecipient:
        """
        Updates a recipient row's attributes.
        """
        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)

        db.add(db_obj)
        if commit:
            await db.commit()
            await db.refresh(db_obj)
        else:
            await db.flush()
        return db_obj

    async def delete(self, db: AsyncSession, db_obj: CampaignRecipient, commit: bool = True) -> bool:
        """
        Hard deletes a recipient row. See the class docstring for why this is not a soft
        delete.
        """
        await db.delete(db_obj)
        if commit:
            await db.commit()
        else:
            await db.flush()
        return True
