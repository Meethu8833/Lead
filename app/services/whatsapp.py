"""
app/services/whatsapp.py

This file implements the services for the WhatsApp Campaign Management module:
WhatsAppTemplateService, WhatsAppCampaignService and CampaignReplyService.
Under Clean Architecture, this file belongs to the Application Business Rules (Use Cases)
layer. It composes repositories, enforces the module's business rules, raises
`AppException` subclasses, and owns transaction boundaries.

Division of responsibility
--------------------------
- `WhatsAppTemplateService` owns template CRUD and the render/variable-substitution rules.
  It is the only place that knows how a `{{placeholder}}` becomes text.
- `WhatsAppCampaignService` owns campaign CRUD, recipient enrolment, the lifecycle state
  machine, dispatch (via the provider port), delivery-status transitions, counter
  maintenance and statistics.
- `CampaignReplyService` owns the inbound path: matching a reply to a recipient, appending
  the lead timeline entry, stamping `Lead.last_contacted_at`, and applying the reply →
  lead-status automation.

The campaign services never import a concrete provider. They depend on the
`WhatsAppProvider` port in `app/services/whatsapp_provider.py`, which is injected at
construction so tests can substitute a failing or recording double.

Timeline integration
--------------------
Every outbound dispatch and every inbound reply appends a `LeadActivity` through the
existing `LeadActivityService`, reusing the `WHATSAPP_SENT` / `WHATSAPP_DELIVERED` /
`WHATSAPP_READ` / `WHATSAPP_REPLIED` activity types that the Lead Activity module already
defined and reserved for exactly this purpose. The campaign module therefore adds no new
timeline concepts — it finally emits the ones that were waiting for it.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.models.lead import Lead, LeadStatus
from app.models.lead_activity import ActivityType
from app.models.whatsapp import (
    WhatsAppTemplate,
    WhatsAppCampaign,
    CampaignRecipient,
    CampaignStatus,
    MessageStatus,
    MESSAGE_STATUS_RANK,
)
from app.repositories.lead import LeadRepository
from app.repositories.whatsapp import (
    WhatsAppTemplateRepository,
    WhatsAppCampaignRepository,
    CampaignRecipientRepository,
)
from app.schemas.whatsapp import (
    WhatsAppTemplateCreate,
    WhatsAppTemplateUpdate,
    WhatsAppCampaignCreate,
    WhatsAppCampaignUpdate,
    CampaignStatisticsResponse,
    extract_template_variables,
    TEMPLATE_VARIABLE_PATTERN,
)
from app.services.lead_activity import LeadActivityService, resolve_actor_employee_id
from app.services.whatsapp_provider import WhatsAppProvider, get_whatsapp_provider

logger = logging.getLogger(__name__)


# Legal campaign lifecycle transitions. Anything not listed is rejected with a 400 rather
# than silently allowed, so a campaign cannot be restarted after completion or edited back
# out of a terminal state.
_ALLOWED_CAMPAIGN_TRANSITIONS: dict[CampaignStatus, set[CampaignStatus]] = {
    CampaignStatus.DRAFT: {CampaignStatus.SCHEDULED, CampaignStatus.RUNNING, CampaignStatus.CANCELLED},
    # SCHEDULED -> SCHEDULED is legal: re-scheduling a campaign to a different time is an
    # ordinary operation, not a state change, and refusing it would force an operator to
    # bounce the campaign back to DRAFT just to move it by an hour.
    CampaignStatus.SCHEDULED: {
        CampaignStatus.SCHEDULED, CampaignStatus.RUNNING,
        CampaignStatus.CANCELLED, CampaignStatus.DRAFT,
    },
    CampaignStatus.RUNNING: {CampaignStatus.COMPLETED, CampaignStatus.CANCELLED},
    CampaignStatus.COMPLETED: set(),
    CampaignStatus.CANCELLED: set(),
}


# Maps a classified reply intent onto the lead status it implies. This is the mapping the
# specification calls for; it lives here as data rather than as branching so an operator
# can see the whole policy at a glance and extend it without touching control flow.
REPLY_TYPE_TO_LEAD_STATUS: dict[str, LeadStatus] = {
    "interested": LeadStatus.NEGOTIATION,
    "not_interested": LeadStatus.LOST,
    "need_details": LeadStatus.REPLIED,
}


# Lead statuses that a reply must never overwrite. A lead that has already converted, or
# been explicitly written off, is past the point where an inbound message should rewrite
# its position in the pipeline — that is a human decision. Without this guard a stray
# "thanks!" after conversion would demote a CUSTOMER back to NEGOTIATION.
_TERMINAL_LEAD_STATUSES: set[LeadStatus] = {LeadStatus.CUSTOMER}


class WhatsAppTemplateService:
    """
    Service layer for reusable WhatsApp message templates.

    Owns two rules that must not live anywhere else: a template's `variables` column is
    always derived from its body, and rendering substitutes only declared placeholders.
    """

    def __init__(
        self,
        repository: WhatsAppTemplateRepository | None = None,
    ) -> None:
        self.repository = repository or WhatsAppTemplateRepository()

    # -----------------------------------------------------------------
    # RENDERING
    # -----------------------------------------------------------------

    @staticmethod
    def render(message_body: str, variables: dict[str, Any] | None) -> tuple[str, list[str]]:
        """
        Substitutes `{{placeholder}}` occurrences in a body with supplied values.

        Returns the rendered text and the list of placeholders that had no value supplied.
        Unmatched placeholders are left in the text verbatim rather than replaced with an
        empty string: a message reading "Hi {{name}}" is an obvious bug that a reviewer
        will catch, whereas "Hi " looks deliberate and would ship.

        Substitution is performed with a single regex pass over the body, so a value that
        itself contains `{{...}}` cannot be re-expanded — there is no recursive rendering
        and therefore no template-injection vector through variable values.
        """
        values = variables or {}
        missing: list[str] = []

        def _replace(match) -> str:
            name = match.group(1)
            if name in values and values[name] is not None:
                return str(values[name])
            if name not in missing:
                missing.append(name)
            return match.group(0)

        rendered = TEMPLATE_VARIABLE_PATTERN.sub(_replace, message_body)
        return rendered, missing

    def build_lead_variables(self, lead: Lead) -> dict[str, Any]:
        """
        Builds the default variable mapping available to every campaign message.

        Campaign sends are personalised from the lead record rather than from
        per-recipient client input, so the placeholder vocabulary a template author may
        use is exactly this set, and it is guaranteed to resolve for any live lead.
        """
        return {
            "business_name": lead.business_name or "",
            "contact_person": lead.contact_person or lead.business_name or "",
            "city": lead.city or "",
            "district": lead.district or "",
            "state": lead.state or "",
            "phone": lead.phone or "",
            "email": lead.email or "",
        }

    # -----------------------------------------------------------------
    # CRUD
    # -----------------------------------------------------------------

    async def create_template(
        self, db: AsyncSession, schema: WhatsAppTemplateCreate
    ) -> WhatsAppTemplate:
        """
        Creates a template.

        Business Rules:
        - Name must be unique among live templates (case-insensitively), so operators
          selecting a template by name never face an ambiguous choice.
        - `variables` is derived from the body, never accepted from the client.
        """
        existing = await self.repository.get_by_name(db, name=schema.name)
        if existing:
            raise BadRequestException(f"A template named '{schema.name}' already exists.")

        template = WhatsAppTemplate(
            name=schema.name,
            category=schema.category,
            language=schema.language,
            message_body=schema.message_body,
            variables=extract_template_variables(schema.message_body),
            is_active=schema.is_active,
        )
        return await self.repository.create(db, template)

    async def get_template_by_id(self, db: AsyncSession, id: uuid.UUID) -> WhatsAppTemplate:
        """
        Retrieves a template by ID. Raises NotFoundException if missing or soft-deleted.
        """
        template = await self.repository.get_by_id(db, id)
        if not template:
            raise NotFoundException(f"WhatsApp template with ID '{id}' was not found.")
        return template

    async def get_all_templates(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        category=None,
        language: str | None = None,
        is_active: bool | None = None,
        search: str | None = None,
    ) -> tuple[Sequence[WhatsAppTemplate], int]:
        """
        Retrieves a paginated, optionally filtered list of templates.
        """
        return await self.repository.get_all(
            db, skip=skip, limit=limit, category=category,
            language=language, is_active=is_active, search=search,
        )

    async def update_template(
        self, db: AsyncSession, id: uuid.UUID, schema: WhatsAppTemplateUpdate
    ) -> WhatsAppTemplate:
        """
        Updates a template.

        Business Rules:
        - Optimistic locking via `version`.
        - A renamed template must still hold a unique name.
        - Editing the body re-derives `variables` so the two never drift.

        Note that editing a template does NOT retroactively change what past campaigns
        sent: each recipient row snapshots its `rendered_message` at dispatch time.
        """
        template = await self.get_template_by_id(db, id)

        if schema.version is not None and template.version != schema.version:
            raise ConflictException("Template was modified by another process. Please reload.")

        update_data = schema.model_dump(exclude_unset=True)
        update_data.pop("version", None)

        new_name = update_data.get("name")
        if new_name and new_name.lower() != template.name.lower():
            existing = await self.repository.get_by_name(db, name=new_name)
            if existing and existing.id != template.id:
                raise BadRequestException(f"A template named '{new_name}' already exists.")

        if "message_body" in update_data:
            update_data["variables"] = extract_template_variables(update_data["message_body"])

        return await self.repository.update(db, db_obj=template, update_data=update_data)

    async def delete_template(self, db: AsyncSession, id: uuid.UUID) -> None:
        """
        Soft deletes a template.

        Business Rules:
        - Refused while any live campaign still references it. Campaigns keep their audit
          value only if the template they sent remains resolvable, and the FK is
          ON DELETE RESTRICT — checking here turns what would be an opaque database error
          into an actionable 400.
        """
        template = await self.get_template_by_id(db, id)

        in_use = await self.repository.count_campaigns_using(db, template_id=id)
        if in_use:
            raise BadRequestException(
                f"Template '{template.name}' is used by {in_use} campaign(s) and cannot be deleted. "
                "Deactivate it instead by setting is_active=false."
            )

        await self.repository.delete(db, db_obj=template)

    async def preview_template(
        self, db: AsyncSession, id: uuid.UUID, variables: dict[str, Any] | None
    ) -> tuple[str, list[str]]:
        """
        Renders a template with caller-supplied sample values, without sending anything.
        """
        template = await self.get_template_by_id(db, id)
        return self.render(template.message_body, variables)


class WhatsAppCampaignService:
    """
    Service layer for campaigns: CRUD, recipient enrolment, lifecycle, dispatch, delivery
    tracking and statistics.
    """

    def __init__(
        self,
        repository: WhatsAppCampaignRepository | None = None,
        recipient_repository: CampaignRecipientRepository | None = None,
        template_repository: WhatsAppTemplateRepository | None = None,
        lead_repository: LeadRepository | None = None,
        template_service: WhatsAppTemplateService | None = None,
        activity_service: LeadActivityService | None = None,
        provider: WhatsAppProvider | None = None,
    ) -> None:
        self.repository = repository or WhatsAppCampaignRepository()
        self.recipient_repository = recipient_repository or CampaignRecipientRepository()
        self.template_repository = template_repository or WhatsAppTemplateRepository()
        self.lead_repository = lead_repository or LeadRepository()
        self.template_service = template_service or WhatsAppTemplateService()
        self.activity_service = activity_service or LeadActivityService()
        # Resolved once per service instance rather than per message: a provider adapter
        # holds a connection pool in the real world, and rebuilding it per recipient would
        # dominate the cost of a large send.
        self.provider = provider or get_whatsapp_provider()

    # -----------------------------------------------------------------
    # HELPERS
    # -----------------------------------------------------------------

    async def _get_campaign_or_404(self, db: AsyncSession, id: uuid.UUID) -> WhatsAppCampaign:
        campaign = await self.repository.get_by_id(db, id)
        if not campaign:
            raise NotFoundException(f"Campaign with ID '{id}' was not found.")
        return campaign

    async def _get_active_template_or_400(
        self, db: AsyncSession, template_id: uuid.UUID
    ) -> WhatsAppTemplate:
        """
        Resolves a template for use by a campaign, rejecting missing or deactivated ones.

        `is_active` is checked at campaign *creation* and at *dispatch*, not in between:
        deactivating a template should stop new sends without invalidating campaigns
        already scheduled around it.
        """
        template = await self.template_repository.get_by_id(db, template_id)
        if not template:
            raise NotFoundException(f"WhatsApp template with ID '{template_id}' was not found.")
        if not template.is_active:
            raise BadRequestException(
                f"Template '{template.name}' is inactive and cannot be used by a campaign."
            )
        return template

    @staticmethod
    def _assert_transition(campaign: WhatsAppCampaign, target: CampaignStatus) -> None:
        """
        Enforces the campaign lifecycle state machine, raising a 400 on an illegal move.
        """
        allowed = _ALLOWED_CAMPAIGN_TRANSITIONS.get(campaign.status, set())
        if target not in allowed:
            raise BadRequestException(
                f"Cannot move campaign from {campaign.status.value} to {target.value}."
            )

    async def _recompute_counters(
        self, db: AsyncSession, campaign: WhatsAppCampaign, commit: bool = True
    ) -> WhatsAppCampaign:
        """
        Recomputes the campaign's denormalized `total_*` columns from its recipient rows.

        The counters are cumulative rather than exclusive: a recipient that has been READ
        also counts as delivered and sent, because "how many were delivered" means "how
        many got that far", not "how many stopped there". Deriving all six from one grouped
        query keeps them internally consistent by construction; incrementing them
        individually at each transition would let a missed webhook desynchronise them
        permanently.
        """
        counts = await self.recipient_repository.status_counts(db, campaign_id=campaign.id)

        def n(status: MessageStatus) -> int:
            return counts.get(status, 0)

        replied = n(MessageStatus.REPLIED)
        read = n(MessageStatus.READ)
        delivered = n(MessageStatus.DELIVERED)
        sent = n(MessageStatus.SENT)
        failed = n(MessageStatus.FAILED)
        queued = n(MessageStatus.QUEUED)
        pending = n(MessageStatus.PENDING)

        cumulative_read = read + replied
        cumulative_delivered = delivered + cumulative_read
        cumulative_sent = sent + cumulative_delivered

        update_data = {
            "total_recipients": pending + queued + sent + delivered + read + failed + replied,
            "total_sent": cumulative_sent,
            "total_delivered": cumulative_delivered,
            "total_read": cumulative_read,
            "total_replied": replied,
            "total_failed": failed,
        }
        return await self.repository.update(db, db_obj=campaign, update_data=update_data, commit=commit)

    # -----------------------------------------------------------------
    # CAMPAIGN CRUD
    # -----------------------------------------------------------------

    async def create_campaign(
        self, db: AsyncSession, schema: WhatsAppCampaignCreate
    ) -> WhatsAppCampaign:
        """
        Creates a campaign and, when `lead_ids` are supplied, enrols its audience.

        Business Rules:
        - The template must exist and be active.
        - A campaign with a `scheduled_at` starts life SCHEDULED; without one, DRAFT.
        - Creator attribution comes from the request-scoped audit context, the same source
          the audit-log listener and lead timeline use, so all three agree on who acted.
        - The campaign and its recipient rows commit together: a campaign that claims 500
          recipients but has none enrolled is worse than no campaign at all.
        """
        await self._get_active_template_or_400(db, schema.template_id)

        campaign = WhatsAppCampaign(
            template_id=schema.template_id,
            name=schema.name,
            description=schema.description,
            scheduled_at=schema.scheduled_at,
            status=CampaignStatus.SCHEDULED if schema.scheduled_at else CampaignStatus.DRAFT,
            created_by=await resolve_actor_employee_id(db),
        )
        await self.repository.create(db, campaign, commit=False)

        if schema.lead_ids:
            await self._enrol_leads(db, campaign, schema.lead_ids, commit=False)

        await self._recompute_counters(db, campaign, commit=False)
        await db.commit()
        await db.refresh(campaign)
        return campaign

    async def get_campaign_by_id(self, db: AsyncSession, id: uuid.UUID) -> WhatsAppCampaign:
        """
        Retrieves a campaign by ID. Raises NotFoundException if missing or soft-deleted.
        """
        return await self._get_campaign_or_404(db, id)

    async def get_all_campaigns(
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
    ) -> tuple[Sequence[WhatsAppCampaign], int]:
        """
        Retrieves a paginated, optionally filtered list of campaigns.
        """
        return await self.repository.get_all(
            db, skip=skip, limit=limit, status=status, template_id=template_id,
            created_by=created_by, created_from=created_from, created_to=created_to,
            search=search,
        )

    async def update_campaign(
        self, db: AsyncSession, id: uuid.UUID, schema: WhatsAppCampaignUpdate
    ) -> WhatsAppCampaign:
        """
        Updates a campaign's editable attributes.

        Business Rules:
        - Optimistic locking via `version`.
        - Only DRAFT and SCHEDULED campaigns are editable. Once dispatch has begun the
          campaign is a historical record; changing its template or schedule afterwards
          would make the recipient rows unexplainable.
        - Changing `scheduled_at` on a DRAFT campaign promotes it to SCHEDULED, so the
          schedule a client sets is the schedule that takes effect rather than being
          silently inert.
        """
        campaign = await self._get_campaign_or_404(db, id)

        if schema.version is not None and campaign.version != schema.version:
            raise ConflictException("Campaign was modified by another process. Please reload.")

        if campaign.status not in (CampaignStatus.DRAFT, CampaignStatus.SCHEDULED):
            raise BadRequestException(
                f"A {campaign.status.value} campaign cannot be edited."
            )

        update_data = schema.model_dump(exclude_unset=True)
        update_data.pop("version", None)

        new_template_id = update_data.get("template_id")
        if new_template_id and new_template_id != campaign.template_id:
            await self._get_active_template_or_400(db, new_template_id)

        if update_data.get("scheduled_at") and campaign.status == CampaignStatus.DRAFT:
            update_data["status"] = CampaignStatus.SCHEDULED

        return await self.repository.update(db, db_obj=campaign, update_data=update_data)

    async def delete_campaign(self, db: AsyncSession, id: uuid.UUID) -> None:
        """
        Soft deletes a campaign.

        Business Rules:
        - A RUNNING campaign must be cancelled before it can be deleted, so a dispatch in
          flight is never orphaned by a delete.
        """
        campaign = await self._get_campaign_or_404(db, id)
        if campaign.status == CampaignStatus.RUNNING:
            raise BadRequestException(
                "A running campaign cannot be deleted. Cancel it first."
            )
        await self.repository.delete(db, db_obj=campaign)

    # -----------------------------------------------------------------
    # RECIPIENTS
    # -----------------------------------------------------------------

    async def _enrol_leads(
        self,
        db: AsyncSession,
        campaign: WhatsAppCampaign,
        lead_ids: Sequence[uuid.UUID],
        commit: bool = True,
    ) -> list[CampaignRecipient]:
        """
        Creates recipient rows for the given leads, skipping ones already enrolled.

        De-duplication happens in memory against a single query for the campaign's existing
        recipients rather than one existence check per lead, so enrolling 10,000 leads
        costs two queries instead of 10,001. The (campaign_id, lead_id) unique constraint
        remains the backstop against a concurrent double-enrolment.

        Soft-deleted or unknown lead IDs are silently skipped rather than raising: a bulk
        enrolment of a saved segment should not fail wholesale because one lead was deleted
        since the segment was built. The count of rows actually created is what the caller
        sees reflected in `total_recipients`.
        """
        requested = list(dict.fromkeys(lead_ids))  # de-duplicate the request itself, order-preserving
        eligible = await self.recipient_repository.get_eligible_leads(db, lead_ids=requested)
        eligible_by_id = {lead.id: lead for lead in eligible}

        existing = await self.recipient_repository.get_all_for_campaign(db, campaign_id=campaign.id)
        already_enrolled = {r.lead_id for r in existing}

        new_recipients = [
            CampaignRecipient(
                campaign_id=campaign.id,
                lead_id=lead_id,
                phone=(eligible_by_id[lead_id].whatsapp or eligible_by_id[lead_id].phone),
                message_status=MessageStatus.PENDING,
            )
            for lead_id in requested
            if lead_id in eligible_by_id and lead_id not in already_enrolled
        ]

        skipped = len(requested) - len(new_recipients)
        if skipped:
            logger.info(
                "Campaign %s: enrolled %d lead(s), skipped %d (already enrolled, deleted or unknown).",
                campaign.id, len(new_recipients), skipped,
            )

        return await self.recipient_repository.bulk_create(db, new_recipients, commit=commit)

    async def add_recipients(
        self, db: AsyncSession, campaign_id: uuid.UUID, lead_ids: Sequence[uuid.UUID]
    ) -> tuple[WhatsAppCampaign, int]:
        """
        Enrols additional leads into an existing campaign, returning the campaign and the
        number of recipients actually added.

        Business Rules:
        - Only DRAFT and SCHEDULED campaigns accept new recipients. Adding an audience
          mid-dispatch would make the run's own totals a moving target.
        """
        campaign = await self._get_campaign_or_404(db, campaign_id)
        if campaign.status not in (CampaignStatus.DRAFT, CampaignStatus.SCHEDULED):
            raise BadRequestException(
                f"Recipients cannot be added to a {campaign.status.value} campaign."
            )

        added = await self._enrol_leads(db, campaign, lead_ids, commit=False)
        await self._recompute_counters(db, campaign, commit=False)
        await db.commit()
        await db.refresh(campaign)
        return campaign, len(added)

    async def get_recipients(
        self,
        db: AsyncSession,
        campaign_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
        message_status: MessageStatus | None = None,
    ) -> tuple[Sequence[CampaignRecipient], int]:
        """
        Returns a campaign's recipients, paginated and optionally filtered by status.
        Raises NotFoundException if the campaign does not exist.
        """
        await self._get_campaign_or_404(db, campaign_id)
        return await self.recipient_repository.get_by_campaign(
            db, campaign_id=campaign_id, skip=skip, limit=limit, message_status=message_status
        )

    async def remove_recipient(
        self, db: AsyncSession, campaign_id: uuid.UUID, recipient_id: uuid.UUID
    ) -> WhatsAppCampaign:
        """
        Removes a not-yet-messaged recipient from a campaign.

        Business Rules:
        - Only a PENDING recipient may be removed. Once a message has been queued or sent,
          the row is a delivery record; deleting it would erase evidence that a lead was
          contacted.
        """
        campaign = await self._get_campaign_or_404(db, campaign_id)

        recipient = await self.recipient_repository.get_by_id(db, recipient_id)
        if not recipient or recipient.campaign_id != campaign_id:
            raise NotFoundException(f"Recipient with ID '{recipient_id}' was not found in this campaign.")

        if recipient.message_status != MessageStatus.PENDING:
            raise BadRequestException(
                f"Recipient has status {recipient.message_status.value} and can no longer be removed."
            )

        await self.recipient_repository.delete(db, db_obj=recipient, commit=False)
        await self._recompute_counters(db, campaign, commit=False)
        await db.commit()
        await db.refresh(campaign)
        return campaign

    # -----------------------------------------------------------------
    # LIFECYCLE
    # -----------------------------------------------------------------

    async def schedule_campaign(
        self, db: AsyncSession, campaign_id: uuid.UUID, scheduled_at: datetime
    ) -> WhatsAppCampaign:
        """
        Moves a campaign to SCHEDULED for a future time.
        """
        campaign = await self._get_campaign_or_404(db, campaign_id)
        self._assert_transition(campaign, CampaignStatus.SCHEDULED)

        aware = scheduled_at if scheduled_at.tzinfo else scheduled_at.replace(tzinfo=timezone.utc)
        if aware <= datetime.now(timezone.utc):
            raise BadRequestException("scheduled_at must be in the future.")

        return await self.repository.update(
            db, db_obj=campaign,
            update_data={"scheduled_at": aware, "status": CampaignStatus.SCHEDULED},
        )

    async def cancel_campaign(self, db: AsyncSession, campaign_id: uuid.UUID) -> WhatsAppCampaign:
        """
        Cancels a campaign. Recipients already messaged keep their delivery records;
        only their campaign stops dispatching.
        """
        campaign = await self._get_campaign_or_404(db, campaign_id)
        self._assert_transition(campaign, CampaignStatus.CANCELLED)
        return await self.repository.update(
            db, db_obj=campaign,
            update_data={"status": CampaignStatus.CANCELLED, "completed_at": datetime.now(timezone.utc)},
        )

    async def start_campaign(self, db: AsyncSession, campaign_id: uuid.UUID) -> dict[str, Any]:
        """
        Dispatches a campaign: renders the template per recipient, hands each message to
        the provider, records the outcome, appends a WHATSAPP_SENT timeline entry per
        successfully-sent lead, and stamps `Lead.last_contacted_at`.

        Business Rules:
        - Only DRAFT and SCHEDULED campaigns may be started (enforced by the transition
          table); starting a COMPLETED one is a 400, not a silent re-send.
        - The campaign must have at least one recipient — dispatching an empty audience is
          almost always a mistake the operator wants told about.
        - The template is re-validated as active at dispatch time, so deactivating a
          template does stop a scheduled campaign from going out.
        - Only PENDING recipients are dispatched. Re-running a partially-failed campaign
          therefore never double-sends to a lead that already received the message.
        - One recipient's failure never aborts the run: a provider exception is caught per
          recipient, recorded as FAILED with its reason, and the loop continues. This is
          the same fault-tolerance posture the run either succeeds wholesale or is
          diagnosable per row.
        - The whole run commits once at the end, so a crash mid-dispatch rolls back to a
          consistent state rather than leaving counters describing a run that half-happened.

        Dispatch is synchronous within the request. That is a deliberate limitation of this
        phase: there is no task queue in this codebase yet, and a background worker would
        be the first thing to add when real provider latency (~100ms/message) makes a
        large audience exceed a request timeout. The provider port is already async, so
        moving this loop into a worker later requires no interface change.
        """
        campaign = await self._get_campaign_or_404(db, campaign_id)
        self._assert_transition(campaign, CampaignStatus.RUNNING)

        template = await self._get_active_template_or_400(db, campaign.template_id)

        recipients = await self.recipient_repository.get_all_for_campaign(
            db, campaign_id=campaign_id, message_status=MessageStatus.PENDING
        )
        if not recipients:
            total = await self.recipient_repository.status_counts(db, campaign_id=campaign_id)
            if not total:
                raise BadRequestException(
                    "Campaign has no recipients. Enrol leads before starting it."
                )
            raise BadRequestException(
                "Campaign has no pending recipients left to dispatch."
            )

        # Mark RUNNING before the loop so a concurrent second Start observes the state
        # change and is rejected by the transition table rather than double-sending.
        await self.repository.update(
            db, db_obj=campaign,
            update_data={"status": CampaignStatus.RUNNING, "started_at": datetime.now(timezone.utc)},
            commit=False,
        )

        # One query for every lead in the audience, instead of one per recipient.
        leads = await self.recipient_repository.get_eligible_leads(
            db, lead_ids=[r.lead_id for r in recipients]
        )
        leads_by_id = {lead.id: lead for lead in leads}

        succeeded = 0
        failed = 0
        now = datetime.now(timezone.utc)

        for recipient in recipients:
            lead = leads_by_id.get(recipient.lead_id)
            if lead is None:
                # The lead was soft-deleted between enrolment and dispatch. Record the
                # reason on the row rather than skipping silently.
                await self.recipient_repository.update(
                    db, db_obj=recipient,
                    update_data={
                        "message_status": MessageStatus.FAILED,
                        "error_message": "Lead no longer exists or was deleted.",
                    },
                    commit=False,
                )
                failed += 1
                continue

            rendered, missing = self.template_service.render(
                template.message_body, self.template_service.build_lead_variables(lead)
            )
            if missing:
                logger.warning(
                    "Campaign %s, lead %s: template placeholders left unsubstituted: %s",
                    campaign.id, lead.id, missing,
                )

            # Reset per iteration: `error_text` is only assigned in the except branch, and
            # a value left over from an earlier failed recipient must never be attributed
            # to this one.
            error_text = "Provider error."
            try:
                result = await self.provider.send_message(
                    recipient.phone,
                    rendered,
                    template_name=template.name,
                    language=template.language,
                )
            except Exception as exc:  # noqa: BLE001 - one bad recipient must not abort the run
                logger.exception(
                    "Campaign %s: provider raised while sending to recipient %s",
                    campaign.id, recipient.id,
                )
                result = None
                error_text = f"Provider error: {exc}"

            if result is not None and result.success:
                await self.recipient_repository.update(
                    db, db_obj=recipient,
                    update_data={
                        "message_status": MessageStatus.SENT,
                        "rendered_message": rendered,
                        "provider_message_id": result.message_id,
                        "sent_at": now,
                        "error_message": None,
                    },
                    commit=False,
                )
                # The timeline entry and the last-contacted stamp are the CRM-visible half
                # of a send; without them a campaign would be invisible on the lead record.
                await self.activity_service.record(
                    db,
                    lead_id=lead.id,
                    activity_type=ActivityType.WHATSAPP_SENT,
                    title=f"WhatsApp message sent: {campaign.name}",
                    description=rendered,
                    metadata={
                        "campaign_id": str(campaign.id),
                        "campaign_name": campaign.name,
                        "template_id": str(template.id),
                        "template_name": template.name,
                        "recipient_id": str(recipient.id),
                        "phone": recipient.phone,
                        "provider": self.provider.name,
                        "provider_message_id": result.message_id,
                    },
                    commit=False,
                )
                # Written directly rather than through LeadRepository.update: that method
                # commits unconditionally, which would break this run's single-transaction
                # guarantee. Assigning on the already-loaded instance keeps the write in
                # the same unit of work as everything else above.
                lead.last_contacted_at = now
                db.add(lead)
                succeeded += 1
            else:
                await self.recipient_repository.update(
                    db, db_obj=recipient,
                    update_data={
                        "message_status": MessageStatus.FAILED,
                        "rendered_message": rendered,
                        "error_message": (
                            error_text if result is None
                            else (result.error or "Provider rejected the message.")
                        ),
                    },
                    commit=False,
                )
                failed += 1

        # A run that dispatched every pending recipient is COMPLETED. If some remain
        # (impossible today, but true once dispatch is batched into a worker), the campaign
        # stays RUNNING so the next batch can pick it up.
        remaining = await self.recipient_repository.status_counts(db, campaign_id=campaign_id)
        still_pending = remaining.get(MessageStatus.PENDING, 0) + remaining.get(MessageStatus.QUEUED, 0)
        if not still_pending:
            await self.repository.update(
                db, db_obj=campaign,
                update_data={"status": CampaignStatus.COMPLETED, "completed_at": datetime.now(timezone.utc)},
                commit=False,
            )

        await self._recompute_counters(db, campaign, commit=False)
        await db.commit()
        await db.refresh(campaign)

        logger.info(
            "Campaign %s dispatched via '%s': %d succeeded, %d failed.",
            campaign.id, self.provider.name, succeeded, failed,
        )
        return {
            "campaign": campaign,
            "dispatched": succeeded + failed,
            "succeeded": succeeded,
            "failed": failed,
            "provider": self.provider.name,
        }

    # -----------------------------------------------------------------
    # DELIVERY STATUS TRACKING
    # -----------------------------------------------------------------

    async def apply_delivery_status(
        self,
        db: AsyncSession,
        provider_message_id: str,
        status: MessageStatus,
        error_message: str | None = None,
        occurred_at: datetime | None = None,
    ) -> CampaignRecipient:
        """
        Applies a provider delivery callback (sent/delivered/read/failed) to a recipient.

        Business Rules:
        - Status only ever moves forward, per MESSAGE_STATUS_RANK. Providers deliver
          webhooks out of order and retry them, so a "delivered" callback arriving after
          a "read" one must be a no-op rather than a regression. This makes the endpoint
          idempotent under replay, which is the property webhook delivery actually needs.
        - The matching timestamp column is stamped only on a real forward transition, so a
          replayed webhook cannot rewrite when something happened.
        """
        recipient = await self.recipient_repository.get_by_provider_message_id(
            db, provider_message_id=provider_message_id
        )
        if not recipient:
            raise NotFoundException(
                f"No campaign recipient matches provider message ID '{provider_message_id}'."
            )

        when = occurred_at or datetime.now(timezone.utc)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)

        current_rank = MESSAGE_STATUS_RANK[recipient.message_status]
        if MESSAGE_STATUS_RANK[status] <= current_rank:
            logger.info(
                "Ignoring out-of-order delivery webhook for recipient %s: %s does not advance %s.",
                recipient.id, status.value, recipient.message_status.value,
            )
            return recipient

        update_data: dict[str, Any] = {"message_status": status}
        timestamp_column = {
            MessageStatus.SENT: "sent_at",
            MessageStatus.DELIVERED: "delivered_at",
            MessageStatus.READ: "read_at",
        }.get(status)
        if timestamp_column:
            update_data[timestamp_column] = when
        if status == MessageStatus.FAILED:
            update_data["error_message"] = error_message or "Provider reported delivery failure."

        await self.recipient_repository.update(db, db_obj=recipient, update_data=update_data, commit=False)

        # A delivery milestone is worth a timeline entry so the lead record shows the
        # message actually landed, not merely that it was sent.
        activity_type = {
            MessageStatus.DELIVERED: ActivityType.WHATSAPP_DELIVERED,
            MessageStatus.READ: ActivityType.WHATSAPP_READ,
        }.get(status)
        if activity_type:
            await self.activity_service.record(
                db,
                lead_id=recipient.lead_id,
                activity_type=activity_type,
                title=f"WhatsApp message {status.value.lower()}",
                description=None,
                metadata={
                    "campaign_id": str(recipient.campaign_id),
                    "recipient_id": str(recipient.id),
                    "provider_message_id": provider_message_id,
                },
                commit=False,
            )

        campaign = await self.repository.get_by_id(db, recipient.campaign_id)
        if campaign:
            await self._recompute_counters(db, campaign, commit=False)

        await db.commit()
        await db.refresh(recipient)
        return recipient

    # -----------------------------------------------------------------
    # STATISTICS
    # -----------------------------------------------------------------

    async def get_statistics(
        self, db: AsyncSession, campaign_id: uuid.UUID
    ) -> CampaignStatisticsResponse:
        """
        Computes a campaign's delivery statistics from its recipient rows.

        Rates are cumulative for the same reason the counters are (see
        `_recompute_counters`): a lead who replied also received and read the message, so
        counting them only under "replied" would make the delivery rate understate reality.

        `progress_percent` measures dispatch completion — the share of recipients no longer
        awaiting a send — which is what a progress bar on a running campaign should track.
        A campaign with no recipients reports 0.0 across the board rather than dividing by
        zero.
        """
        campaign = await self._get_campaign_or_404(db, campaign_id)
        counts = await self.recipient_repository.status_counts(db, campaign_id=campaign_id)

        def n(status: MessageStatus) -> int:
            return counts.get(status, 0)

        pending = n(MessageStatus.PENDING)
        queued = n(MessageStatus.QUEUED)
        sent = n(MessageStatus.SENT)
        delivered = n(MessageStatus.DELIVERED)
        read = n(MessageStatus.READ)
        failed = n(MessageStatus.FAILED)
        replied = n(MessageStatus.REPLIED)

        total = pending + queued + sent + delivered + read + failed + replied

        cumulative_read = read + replied
        cumulative_delivered = delivered + cumulative_read
        dispatched = total - pending - queued

        def pct(part: int) -> float:
            return round((part / total) * 100, 2) if total else 0.0

        return CampaignStatisticsResponse(
            campaign_id=campaign.id,
            campaign_name=campaign.name,
            status=campaign.status,
            total_recipients=total,
            pending=pending,
            queued=queued,
            sent=sent,
            delivered=delivered,
            read=read,
            failed=failed,
            replied=replied,
            delivery_rate=pct(cumulative_delivered),
            read_rate=pct(cumulative_read),
            reply_rate=pct(replied),
            failure_rate=pct(failed),
            progress_percent=pct(dispatched),
        )


class CampaignReplyService:
    """
    Service layer for the inbound path: recording a lead's reply to a campaign message.

    This is the only service in the module that writes to `Lead`, and it is deliberately
    separated from `WhatsAppCampaignService` because the two have opposite risk profiles:
    the outbound side talks to a third party and may fail per message, while this side
    mutates CRM state that the sales team relies on and must therefore be conservative
    about what it is willing to overwrite.
    """

    def __init__(
        self,
        recipient_repository: CampaignRecipientRepository | None = None,
        campaign_repository: WhatsAppCampaignRepository | None = None,
        lead_repository: LeadRepository | None = None,
        activity_service: LeadActivityService | None = None,
        campaign_service: WhatsAppCampaignService | None = None,
    ) -> None:
        self.recipient_repository = recipient_repository or CampaignRecipientRepository()
        self.campaign_repository = campaign_repository or WhatsAppCampaignRepository()
        self.lead_repository = lead_repository or LeadRepository()
        self.activity_service = activity_service or LeadActivityService()
        self.campaign_service = campaign_service or WhatsAppCampaignService()

    @staticmethod
    def resolve_lead_status(
        reply_type: str | None,
        explicit: LeadStatus | None,
        current: LeadStatus,
    ) -> LeadStatus | None:
        """
        Decides what status a reply should move a lead to, or None to leave it alone.

        Precedence: an explicit `lead_status` from the caller wins over the `reply_type`
        mapping, because a human classification is better evidence than a keyword rule.
        An unrecognised `reply_type` maps to nothing rather than to a default, so a new
        intent label added upstream cannot silently reclassify leads.

        A lead already in a terminal status (see `_TERMINAL_LEAD_STATUSES`) is never moved,
        and a mapping that resolves to the lead's current status returns None so the caller
        can skip an empty write and an empty timeline entry.
        """
        if current in _TERMINAL_LEAD_STATUSES:
            return None

        target = explicit if explicit is not None else (
            REPLY_TYPE_TO_LEAD_STATUS.get(reply_type) if reply_type else None
        )
        if target is None or target == current:
            return None
        return target

    async def _match_recipient(
        self,
        db: AsyncSession,
        provider_message_id: str | None,
        phone: str | None,
    ) -> CampaignRecipient:
        """
        Resolves the recipient row a reply belongs to.

        Prefers the provider's message ID, which pins the reply to an exact outbound
        message. Falls back to the sender's number matched against its most recent
        dispatch, which is all some providers give us.
        """
        if provider_message_id:
            recipient = await self.recipient_repository.get_by_provider_message_id(
                db, provider_message_id=provider_message_id
            )
            if recipient:
                return recipient
            raise NotFoundException(
                f"No campaign recipient matches provider message ID '{provider_message_id}'."
            )

        if phone:
            recipient = await self.recipient_repository.get_latest_for_phone(db, phone=phone.strip())
            if recipient:
                return recipient
            raise NotFoundException(
                f"No dispatched campaign message was found for phone '{phone}'."
            )

        raise BadRequestException(
            "A reply must identify its message by either provider_message_id or phone."
        )

    async def record_reply(
        self,
        db: AsyncSession,
        reply_text: str,
        provider_message_id: str | None = None,
        phone: str | None = None,
        reply_type: str | None = None,
        lead_status: LeadStatus | None = None,
        replied_at: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Records an inbound reply and runs the CRM automation it triggers.

        Everything this does happens in one transaction:
        1. The recipient row moves to REPLIED, storing the body and timestamp.
        2. A WHATSAPP_REPLIED entry is appended to the lead's timeline.
        3. `Lead.last_contacted_at` is stamped.
        4. The lead's status is updated per the reply-type mapping, when applicable, and a
           STATUS_CHANGED entry is appended alongside it.
        5. The campaign's counters are recomputed.

        Steps 2-4 are what make a reply a CRM event rather than a log line, and committing
        them together is why: a lead whose status says NEGOTIATION but whose timeline has
        no reply explaining why is exactly the inconsistency that erodes trust in a CRM.

        Recording a reply is idempotent in status terms — REPLIED is the top of
        MESSAGE_STATUS_RANK, so a re-delivered webhook overwrites the body and timestamp
        with identical values rather than corrupting state. It does append a second
        timeline entry, which is correct: two replies from a lead are two events.
        """
        recipient = await self._match_recipient(db, provider_message_id, phone)

        when = replied_at or datetime.now(timezone.utc)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)

        lead = await self.lead_repository.get_by_id(db, recipient.lead_id)
        if not lead:
            raise NotFoundException(
                f"The lead behind recipient '{recipient.id}' no longer exists."
            )

        campaign = await self.campaign_repository.get_by_id(db, recipient.campaign_id)

        # 1. The delivery record.
        await self.recipient_repository.update(
            db, db_obj=recipient,
            update_data={
                "message_status": MessageStatus.REPLIED,
                "reply_text": reply_text,
                "replied_at": when,
            },
            commit=False,
        )

        # 2. The timeline entry.
        activity = await self.activity_service.record(
            db,
            lead_id=lead.id,
            activity_type=ActivityType.WHATSAPP_REPLIED,
            title="WhatsApp reply received",
            description=reply_text,
            metadata={
                "campaign_id": str(recipient.campaign_id),
                "campaign_name": campaign.name if campaign else None,
                "recipient_id": str(recipient.id),
                "phone": recipient.phone,
                "reply_type": reply_type,
                "provider_message_id": recipient.provider_message_id,
            },
            commit=False,
        )

        # 3 & 4. The lead record: contact stamp, and the status automation.
        old_status = lead.status
        new_status = self.resolve_lead_status(reply_type, lead_status, old_status)

        lead.last_contacted_at = when
        if new_status is not None:
            lead.status = new_status
        db.add(lead)
        await db.flush()

        if new_status is not None:
            await self.activity_service.log_status_changed(
                db, lead, old_status, new_status, commit=False
            )

        # 5. The campaign's counters.
        if campaign:
            await self.campaign_service._recompute_counters(db, campaign, commit=False)

        await db.commit()
        await db.refresh(recipient)
        await db.refresh(lead)

        logger.info(
            "Recorded reply for lead %s (recipient %s); status %s -> %s.",
            lead.id, recipient.id, old_status.value,
            lead.status.value if lead.status else None,
        )

        return {
            "recipient": recipient,
            "lead_id": lead.id,
            "lead_status": lead.status,
            "lead_status_changed": new_status is not None,
            "activity_id": activity.id if activity else None,
        }
