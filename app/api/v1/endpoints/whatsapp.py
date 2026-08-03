"""
app/api/v1/endpoints/whatsapp.py

This file defines the API routes (Endpoints) for the WhatsApp Campaign Management module.
Under Clean Architecture, this file resides in the Interface Adapters layer. It acts as the
HTTP controller: parsing requests, delegating execution to the Service layer, and returning
structured JSON responses matching our Pydantic schemas.

RBAC
----
Every route is protected by the existing `RequirePermission` dependency using a dedicated
`whatsapp:*` permission set (`whatsapp:view` / `create` / `update` / `delete`), seeded by
`scripts/seed_roles.py`. Outbound messaging is a distinct capability from lead editing —
a receptionist who may correct a phone number should not thereby be able to blast 5,000
leads — so unlike lead notes, this module does NOT reuse `leads:*`.

The reply webhook is the one endpoint that a third party (not a logged-in employee) will
eventually call. It is protected by `whatsapp:update` for now, which means it is reachable
only by an authenticated operator or an internal integration holding a token. A real
provider integration cannot present a JWT and will instead need signature verification
(Meta's `X-Hub-Signature-256`, Twilio's `X-Twilio-Signature`); that verification is
provider-specific and belongs with the provider adapter, so it is deliberately deferred
along with the adapter itself rather than guessed at now. Leaving the endpoint behind RBAC
in the meantime is the safe default: an unauthenticated webhook with no signature check
would let anyone on the internet rewrite lead statuses.
"""

import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_db,
    get_whatsapp_template_service,
    get_whatsapp_campaign_service,
    get_campaign_reply_service,
    RequirePermission,
)
from app.models.whatsapp import TemplateCategory, CampaignStatus, MessageStatus
from app.schemas.whatsapp import (
    WhatsAppTemplateCreate,
    WhatsAppTemplateUpdate,
    WhatsAppTemplateResponse,
    WhatsAppTemplateListResponse,
    TemplatePreviewRequest,
    TemplatePreviewResponse,
    WhatsAppCampaignCreate,
    WhatsAppCampaignUpdate,
    WhatsAppCampaignResponse,
    WhatsAppCampaignListResponse,
    CampaignRecipientAddRequest,
    CampaignRecipientListResponse,
    CampaignStartResponse,
    CampaignStatisticsResponse,
    ReplyWebhookRequest,
    ReplyRecordedResponse,
    DeliveryStatusWebhookRequest,
    CampaignRecipientResponse,
)
from app.services.whatsapp import (
    WhatsAppTemplateService,
    WhatsAppCampaignService,
    CampaignReplyService,
)

router = APIRouter()


# =====================================================================
# TEMPLATES
# =====================================================================

@router.get(
    "/templates",
    response_model=WhatsAppTemplateListResponse,
    status_code=status.HTTP_200_OK,
    summary="List message templates",
    description="Fetches a paginated list of WhatsApp message templates, newest first, with optional category/language/active filters and full-text search over name and body.",
    dependencies=[Depends(RequirePermission("whatsapp:view"))],
)
async def list_templates(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    category: TemplateCategory | None = Query(None, description="Filter by business category"),
    language: str | None = Query(None, description="Filter by language code"),
    is_active: bool | None = Query(None, description="Filter by active flag"),
    search: str | None = Query(None, description="Case-insensitive partial match on name or message body"),
    db: AsyncSession = Depends(get_db),
    service: WhatsAppTemplateService = Depends(get_whatsapp_template_service),
) -> WhatsAppTemplateListResponse:
    """
    GET /whatsapp/templates Endpoint Flow:
    Query params -> Service -> Repository -> paginated templates + total count.
    """
    items, total = await service.get_all_templates(
        db=db, skip=skip, limit=limit, category=category,
        language=language, is_active=is_active, search=search,
    )
    return WhatsAppTemplateListResponse(items=items, total=total, skip=skip, limit=limit)


@router.post(
    "/templates",
    response_model=WhatsAppTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a message template",
    description="Creates a reusable message template. The `variables` list is derived from the {{placeholders}} in the body and is not accepted from the client. Template names must be unique among live templates.",
    dependencies=[Depends(RequirePermission("whatsapp:create"))],
)
async def create_template(
    schema: WhatsAppTemplateCreate,
    db: AsyncSession = Depends(get_db),
    service: WhatsAppTemplateService = Depends(get_whatsapp_template_service),
) -> WhatsAppTemplateResponse:
    """
    POST /whatsapp/templates Endpoint Flow:
    Client JSON -> Validation -> Service (uniqueness + variable extraction) -> created template.
    """
    return await service.create_template(db=db, schema=schema)


@router.get(
    "/templates/{id}",
    response_model=WhatsAppTemplateResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a template",
    description="Fetches a single template by ID. Raises 404 if it does not exist or was deleted.",
    dependencies=[Depends(RequirePermission("whatsapp:view"))],
)
async def get_template(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: WhatsAppTemplateService = Depends(get_whatsapp_template_service),
) -> WhatsAppTemplateResponse:
    """
    GET /whatsapp/templates/{id} Endpoint Flow:
    Service -> Repository -> template, or 404.
    """
    return await service.get_template_by_id(db=db, id=id)


@router.put(
    "/templates/{id}",
    response_model=WhatsAppTemplateResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a template",
    description="Partially updates a template. Supply `version` for optimistic locking (409 on conflict). Editing the body re-derives the variable list; it does not change what past campaigns already sent.",
    dependencies=[Depends(RequirePermission("whatsapp:update"))],
)
async def update_template(
    id: uuid.UUID,
    schema: WhatsAppTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    service: WhatsAppTemplateService = Depends(get_whatsapp_template_service),
) -> WhatsAppTemplateResponse:
    """
    PUT /whatsapp/templates/{id} Endpoint Flow:
    Version check -> name uniqueness -> variable re-derivation -> updated template.
    """
    return await service.update_template(db=db, id=id, schema=schema)


@router.delete(
    "/templates/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a template",
    description="Soft deletes a template. Refused with 400 while any live campaign still references it; deactivate it instead.",
    dependencies=[Depends(RequirePermission("whatsapp:delete"))],
)
async def delete_template(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: WhatsAppTemplateService = Depends(get_whatsapp_template_service),
) -> None:
    """
    DELETE /whatsapp/templates/{id} Endpoint Flow:
    In-use check -> soft delete, or 404/400.
    """
    await service.delete_template(db=db, id=id)


@router.post(
    "/templates/{id}/preview",
    response_model=TemplatePreviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Preview a rendered template",
    description="Renders a template against sample variable values without sending anything, and reports which placeholders were left unsubstituted.",
    dependencies=[Depends(RequirePermission("whatsapp:view"))],
)
async def preview_template(
    id: uuid.UUID,
    schema: TemplatePreviewRequest,
    db: AsyncSession = Depends(get_db),
    service: WhatsAppTemplateService = Depends(get_whatsapp_template_service),
) -> TemplatePreviewResponse:
    """
    POST /whatsapp/templates/{id}/preview Endpoint Flow:
    Service renders the body with the supplied mapping -> rendered text + missing variables.
    """
    rendered, missing = await service.preview_template(db=db, id=id, variables=schema.variables)
    return TemplatePreviewResponse(rendered_message=rendered, missing_variables=missing)


# =====================================================================
# CAMPAIGNS
# =====================================================================

@router.get(
    "/campaigns",
    response_model=WhatsAppCampaignListResponse,
    status_code=status.HTTP_200_OK,
    summary="List campaigns",
    description="Fetches a paginated list of campaigns, newest first, with optional status/template/creator/date filters and search over name and description.",
    dependencies=[Depends(RequirePermission("whatsapp:view"))],
)
async def list_campaigns(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    status_filter: CampaignStatus | None = Query(None, alias="status", description="Filter by lifecycle status"),
    template_id: uuid.UUID | None = Query(None, description="Filter by source template"),
    created_by: uuid.UUID | None = Query(None, description="Filter by the employee who created the campaign"),
    created_from: datetime | None = Query(None, description="Only campaigns created at or after this time"),
    created_to: datetime | None = Query(None, description="Only campaigns created at or before this time"),
    search: str | None = Query(None, description="Case-insensitive partial match on name or description"),
    db: AsyncSession = Depends(get_db),
    service: WhatsAppCampaignService = Depends(get_whatsapp_campaign_service),
) -> WhatsAppCampaignListResponse:
    """
    GET /whatsapp/campaigns Endpoint Flow:
    Query params -> Service -> Repository -> paginated campaigns + total count.
    """
    items, total = await service.get_all_campaigns(
        db=db, skip=skip, limit=limit, status=status_filter, template_id=template_id,
        created_by=created_by, created_from=created_from, created_to=created_to, search=search,
    )
    return WhatsAppCampaignListResponse(items=items, total=total, skip=skip, limit=limit)


@router.post(
    "/campaigns",
    response_model=WhatsAppCampaignResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a campaign",
    description="Creates a campaign against an active template and optionally enrols its audience by lead ID. A campaign with `scheduled_at` starts as SCHEDULED; without one it starts as DRAFT. Unknown or deleted lead IDs are skipped rather than failing the request.",
    dependencies=[Depends(RequirePermission("whatsapp:create"))],
)
async def create_campaign(
    schema: WhatsAppCampaignCreate,
    db: AsyncSession = Depends(get_db),
    service: WhatsAppCampaignService = Depends(get_whatsapp_campaign_service),
) -> WhatsAppCampaignResponse:
    """
    POST /whatsapp/campaigns Endpoint Flow:
    Client JSON -> template validation -> campaign + recipient rows in one transaction.
    """
    return await service.create_campaign(db=db, schema=schema)


@router.get(
    "/campaigns/{id}",
    response_model=WhatsAppCampaignResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a campaign",
    description="Fetches a single campaign by ID, including its denormalized delivery counters. Raises 404 if it does not exist or was deleted.",
    dependencies=[Depends(RequirePermission("whatsapp:view"))],
)
async def get_campaign(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: WhatsAppCampaignService = Depends(get_whatsapp_campaign_service),
) -> WhatsAppCampaignResponse:
    """
    GET /whatsapp/campaigns/{id} Endpoint Flow:
    Service -> Repository -> campaign, or 404.
    """
    return await service.get_campaign_by_id(db=db, id=id)


@router.put(
    "/campaigns/{id}",
    response_model=WhatsAppCampaignResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a campaign",
    description="Partially updates a DRAFT or SCHEDULED campaign. Supply `version` for optimistic locking (409 on conflict). Running, completed and cancelled campaigns are immutable (400).",
    dependencies=[Depends(RequirePermission("whatsapp:update"))],
)
async def update_campaign(
    id: uuid.UUID,
    schema: WhatsAppCampaignUpdate,
    db: AsyncSession = Depends(get_db),
    service: WhatsAppCampaignService = Depends(get_whatsapp_campaign_service),
) -> WhatsAppCampaignResponse:
    """
    PUT /whatsapp/campaigns/{id} Endpoint Flow:
    Version check -> editability check -> template validation -> updated campaign.
    """
    return await service.update_campaign(db=db, id=id, schema=schema)


@router.delete(
    "/campaigns/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a campaign",
    description="Soft deletes a campaign. A RUNNING campaign must be cancelled first (400).",
    dependencies=[Depends(RequirePermission("whatsapp:delete"))],
)
async def delete_campaign(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: WhatsAppCampaignService = Depends(get_whatsapp_campaign_service),
) -> None:
    """
    DELETE /whatsapp/campaigns/{id} Endpoint Flow:
    Running check -> soft delete, or 404/400.
    """
    await service.delete_campaign(db=db, id=id)


@router.post(
    "/campaigns/{id}/start",
    response_model=CampaignStartResponse,
    status_code=status.HTTP_200_OK,
    summary="Start (dispatch) a campaign",
    description=(
        "Dispatches every PENDING recipient of a DRAFT or SCHEDULED campaign through the configured "
        "provider, appends a WHATSAPP_SENT activity per lead, and stamps each lead's last_contacted_at. "
        "Individual send failures are recorded on their recipient row and do not abort the run. "
        "Returns the updated campaign plus a run summary."
    ),
    dependencies=[Depends(RequirePermission("whatsapp:update"))],
)
async def start_campaign(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: WhatsAppCampaignService = Depends(get_whatsapp_campaign_service),
) -> CampaignStartResponse:
    """
    POST /whatsapp/campaigns/{id}/start Endpoint Flow:
    Transition check -> template re-validation -> per-recipient dispatch -> counters -> summary.
    """
    result = await service.start_campaign(db=db, campaign_id=id)
    return CampaignStartResponse(
        campaign=WhatsAppCampaignResponse.model_validate(result["campaign"]),
        dispatched=result["dispatched"],
        succeeded=result["succeeded"],
        failed=result["failed"],
        provider=result["provider"],
    )


@router.post(
    "/campaigns/{id}/cancel",
    response_model=WhatsAppCampaignResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel a campaign",
    description="Cancels a DRAFT, SCHEDULED or RUNNING campaign. Recipients already messaged keep their delivery records.",
    dependencies=[Depends(RequirePermission("whatsapp:update"))],
)
async def cancel_campaign(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: WhatsAppCampaignService = Depends(get_whatsapp_campaign_service),
) -> WhatsAppCampaignResponse:
    """
    POST /whatsapp/campaigns/{id}/cancel Endpoint Flow:
    Transition check -> status set to CANCELLED.
    """
    return await service.cancel_campaign(db=db, campaign_id=id)


@router.get(
    "/campaigns/{id}/statistics",
    response_model=CampaignStatisticsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get campaign statistics",
    description=(
        "Computes delivery statistics from the campaign's recipient rows (authoritative, not read off the "
        "denormalized counters). Rates are cumulative percentages of total recipients: a lead who replied "
        "also counts as delivered and read. Returns zeros for an empty campaign rather than dividing by zero."
    ),
    dependencies=[Depends(RequirePermission("whatsapp:view"))],
)
async def get_campaign_statistics(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: WhatsAppCampaignService = Depends(get_whatsapp_campaign_service),
) -> CampaignStatisticsResponse:
    """
    GET /whatsapp/campaigns/{id}/statistics Endpoint Flow:
    Service aggregates recipient statuses in one grouped query -> counts + rates + progress.
    """
    return await service.get_statistics(db=db, campaign_id=id)


# =====================================================================
# RECIPIENTS
# =====================================================================

@router.get(
    "/campaigns/{id}/recipients",
    response_model=CampaignRecipientListResponse,
    status_code=status.HTTP_200_OK,
    summary="List a campaign's recipients",
    description="Fetches a campaign's recipient rows, oldest enrolment first, optionally filtered to one message status. Raises 404 if the campaign does not exist.",
    dependencies=[Depends(RequirePermission("whatsapp:view"))],
)
async def list_campaign_recipients(
    id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    message_status: MessageStatus | None = Query(None, description="Filter to a single delivery status"),
    db: AsyncSession = Depends(get_db),
    service: WhatsAppCampaignService = Depends(get_whatsapp_campaign_service),
) -> CampaignRecipientListResponse:
    """
    GET /whatsapp/campaigns/{id}/recipients Endpoint Flow:
    Campaign existence check -> Service -> Repository -> paginated recipients + total count.
    """
    items, total = await service.get_recipients(
        db=db, campaign_id=id, skip=skip, limit=limit, message_status=message_status
    )
    return CampaignRecipientListResponse(items=items, total=total, skip=skip, limit=limit)


@router.post(
    "/campaigns/{id}/recipients",
    response_model=WhatsAppCampaignResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add recipients to a campaign",
    description="Enrols additional leads into a DRAFT or SCHEDULED campaign. Already-enrolled, deleted and unknown leads are skipped. Returns the campaign with refreshed counters.",
    dependencies=[Depends(RequirePermission("whatsapp:update"))],
)
async def add_campaign_recipients(
    id: uuid.UUID,
    schema: CampaignRecipientAddRequest,
    db: AsyncSession = Depends(get_db),
    service: WhatsAppCampaignService = Depends(get_whatsapp_campaign_service),
) -> WhatsAppCampaignResponse:
    """
    POST /whatsapp/campaigns/{id}/recipients Endpoint Flow:
    Editability check -> de-duplicated bulk enrolment -> counter recompute -> campaign.
    """
    campaign, _added = await service.add_recipients(db=db, campaign_id=id, lead_ids=schema.lead_ids)
    return campaign


@router.delete(
    "/campaigns/{id}/recipients/{recipient_id}",
    response_model=WhatsAppCampaignResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove a recipient from a campaign",
    description="Removes a still-PENDING recipient. Recipients that have been queued or messaged are delivery records and cannot be removed (400).",
    dependencies=[Depends(RequirePermission("whatsapp:update"))],
)
async def remove_campaign_recipient(
    id: uuid.UUID,
    recipient_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: WhatsAppCampaignService = Depends(get_whatsapp_campaign_service),
) -> WhatsAppCampaignResponse:
    """
    DELETE /whatsapp/campaigns/{id}/recipients/{recipient_id} Endpoint Flow:
    Ownership + status check -> hard delete of the enrolment -> counter recompute.
    """
    return await service.remove_recipient(db=db, campaign_id=id, recipient_id=recipient_id)


# =====================================================================
# WEBHOOKS
# =====================================================================

@router.post(
    "/webhook/reply",
    response_model=ReplyRecordedResponse,
    status_code=status.HTTP_200_OK,
    summary="Record an inbound reply",
    description=(
        "Records a lead's reply to a campaign message. The reply is matched by `provider_message_id` when "
        "available, otherwise by `phone` against that number's most recent dispatch. Recording a reply moves "
        "the recipient to REPLIED, appends a WHATSAPP_REPLIED activity, stamps the lead's last_contacted_at, "
        "and applies the reply-type mapping to the lead's CRM status "
        "(interested -> NEGOTIATION, not_interested -> LOST, need_details -> REPLIED). "
        "Supply `lead_status` to override the mapping. Converted leads are never re-categorised."
    ),
    dependencies=[Depends(RequirePermission("whatsapp:update"))],
)
async def record_reply(
    schema: ReplyWebhookRequest,
    db: AsyncSession = Depends(get_db),
    service: CampaignReplyService = Depends(get_campaign_reply_service),
) -> ReplyRecordedResponse:
    """
    POST /whatsapp/webhook/reply Endpoint Flow:
    Match recipient -> recipient REPLIED + timeline entry + last_contacted_at + status
    automation + counter recompute, all in one transaction -> what actually changed.
    """
    result = await service.record_reply(
        db=db,
        reply_text=schema.reply_text,
        provider_message_id=schema.provider_message_id,
        phone=schema.phone,
        reply_type=schema.reply_type,
        lead_status=schema.lead_status,
        replied_at=schema.replied_at,
    )
    return ReplyRecordedResponse(
        recipient=CampaignRecipientResponse.model_validate(result["recipient"]),
        lead_id=result["lead_id"],
        lead_status=result["lead_status"],
        lead_status_changed=result["lead_status_changed"],
        activity_id=result["activity_id"],
    )


@router.post(
    "/webhook/status",
    response_model=CampaignRecipientResponse,
    status_code=status.HTTP_200_OK,
    summary="Record a delivery-status callback",
    description=(
        "Applies a provider delivery callback (SENT/DELIVERED/READ/FAILED) to the recipient identified by "
        "`provider_message_id`. Status only ever moves forward, so replayed or out-of-order webhooks are "
        "idempotent no-ops rather than regressions. DELIVERED and READ also append a timeline entry."
    ),
    dependencies=[Depends(RequirePermission("whatsapp:update"))],
)
async def record_delivery_status(
    schema: DeliveryStatusWebhookRequest,
    db: AsyncSession = Depends(get_db),
    service: WhatsAppCampaignService = Depends(get_whatsapp_campaign_service),
) -> CampaignRecipientResponse:
    """
    POST /whatsapp/webhook/status Endpoint Flow:
    Match recipient by provider message ID -> monotonic status check -> timestamp + activity
    + counter recompute.
    """
    return await service.apply_delivery_status(
        db=db,
        provider_message_id=schema.provider_message_id,
        status=schema.status,
        error_message=schema.error_message,
        occurred_at=schema.occurred_at,
    )
