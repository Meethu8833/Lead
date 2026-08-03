"""
app/schemas/whatsapp.py

This file defines the Pydantic schemas for the WhatsApp Campaign Management module.
Under Clean Architecture, schemas act as Data Transfer Objects (DTOs) in the Interface
Adapters layer. They validate client inputs (request payloads) and structure client
outputs (response payloads).

Note there is no `CampaignRecipientCreate` that accepts a raw phone number: recipients are
enrolled by lead ID and the number is snapshotted from the lead. Allowing a caller to post
an arbitrary destination number would turn the campaign engine into an open relay with no
link back to a CRM record.
"""

import re
import uuid
from datetime import datetime, timezone
from typing import Any, List
from pydantic import BaseModel, Field, field_validator, ConfigDict

from app.models.lead import LeadStatus
from app.models.whatsapp import TemplateCategory, CampaignStatus, MessageStatus


# Matches the {{variable}} placeholder syntax used in template bodies. Names are restricted
# to identifier characters so a placeholder can never smuggle in formatting or markup.
TEMPLATE_VARIABLE_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def extract_template_variables(message_body: str) -> list[str]:
    """
    Extracts the ordered, de-duplicated list of `{{variable}}` names declared by a body.

    This is the single definition of what a template's variables are. The service derives
    the stored `variables` column from it on every write, so the column can never disagree
    with the body — which is why `WhatsAppTemplateCreate` has no client-supplied variables
    field.
    """
    seen: list[str] = []
    for match in TEMPLATE_VARIABLE_PATTERN.finditer(message_body):
        name = match.group(1)
        if name not in seen:
            seen.append(name)
    return seen


# =====================================================================
# WHATSAPP TEMPLATES
# =====================================================================

class WhatsAppTemplateBase(BaseModel):
    """
    Base Pydantic schema for WhatsAppTemplate shared fields.
    """
    name: str = Field(..., description="Human-readable template name", min_length=1, max_length=255)
    category: TemplateCategory = Field(
        TemplateCategory.MARKETING, description="Business purpose of the template"
    )
    language: str = Field("en", description="Language code for the message body", min_length=2, max_length=10)
    message_body: str = Field(
        ...,
        description="Raw message text; may contain {{variable}} placeholders",
        min_length=1,
        max_length=4096,
    )
    is_active: bool = Field(True, description="Whether the template may be used by new campaigns")

    @field_validator("name")
    @classmethod
    def name_cannot_be_blank(cls, v: str) -> str:
        """
        Validates the name is not just whitespace, and normalizes it by stripping.
        """
        stripped = v.strip()
        if not stripped:
            raise ValueError("Template name cannot be empty or contain only whitespace.")
        return stripped

    @field_validator("message_body")
    @classmethod
    def body_cannot_be_blank(cls, v: str) -> str:
        """
        Validates the message body is not just whitespace, and normalizes it by stripping.
        """
        stripped = v.strip()
        if not stripped:
            raise ValueError("Message body cannot be empty or contain only whitespace.")
        return stripped

    @field_validator("language")
    @classmethod
    def normalize_language(cls, v: str) -> str:
        """
        Normalizes the language code by stripping surrounding whitespace.
        """
        stripped = v.strip()
        if not stripped:
            raise ValueError("Language code cannot be empty.")
        return stripped


class WhatsAppTemplateCreate(WhatsAppTemplateBase):
    """
    Schema for validating requests to create a template.

    `variables` is intentionally absent: it is derived from `message_body` by the service
    (see `extract_template_variables`), so a client cannot declare variables the body does
    not contain, or omit ones it does.
    """
    pass


class WhatsAppTemplateUpdate(BaseModel):
    """
    Schema for validating partial updates to a template.
    All fields optional; `version` drives optimistic locking as on Lead.
    """
    name: str | None = Field(None, min_length=1, max_length=255)
    category: TemplateCategory | None = Field(None)
    language: str | None = Field(None, min_length=2, max_length=10)
    message_body: str | None = Field(None, min_length=1, max_length=4096)
    is_active: bool | None = Field(None)
    version: int | None = Field(None, description="Expected current version, for optimistic locking")

    @field_validator("name", "message_body", "language")
    @classmethod
    def cannot_be_blank(cls, v: str | None) -> str | None:
        """
        Rejects whitespace-only values for any of the text fields, and strips them.
        """
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            raise ValueError("Value cannot be empty or contain only whitespace.")
        return stripped


class WhatsAppTemplateResponse(BaseModel):
    """
    Schema for serializing a WhatsAppTemplate database record into an API response.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: TemplateCategory
    language: str
    message_body: str
    variables: List[str] | None
    is_active: bool
    version: int
    created_at: datetime
    updated_at: datetime


class WhatsAppTemplateListResponse(BaseModel):
    """
    Schema for a paginated list of templates.
    """
    items: List[WhatsAppTemplateResponse]
    total: int = Field(..., description="Total templates matching the filters (ignoring skip/limit)")
    skip: int
    limit: int


class TemplatePreviewRequest(BaseModel):
    """
    Schema for requesting a rendered preview of a template with sample variable values.
    """
    variables: dict[str, Any] = Field(
        default_factory=dict,
        description="Mapping of placeholder name -> value to substitute into the body",
    )


class TemplatePreviewResponse(BaseModel):
    """
    Schema for the rendered result of a template preview.
    `missing_variables` reports placeholders the supplied mapping did not cover, so the
    caller learns what a real send would leave unsubstituted.
    """
    rendered_message: str
    missing_variables: List[str]


# =====================================================================
# WHATSAPP CAMPAIGNS
# =====================================================================

class WhatsAppCampaignBase(BaseModel):
    """
    Base Pydantic schema for WhatsAppCampaign shared fields.
    """
    name: str = Field(..., description="Human-readable campaign name", min_length=1, max_length=255)
    description: str | None = Field(None, description="Purpose of the campaign", max_length=5000)
    scheduled_at: datetime | None = Field(
        None, description="When the campaign should run; omit for an immediate/draft campaign"
    )

    @field_validator("name")
    @classmethod
    def name_cannot_be_blank(cls, v: str) -> str:
        """
        Validates the campaign name is not just whitespace, and normalizes it by stripping.
        """
        stripped = v.strip()
        if not stripped:
            raise ValueError("Campaign name cannot be empty or contain only whitespace.")
        return stripped

    @field_validator("scheduled_at")
    @classmethod
    def scheduled_at_must_be_future(cls, v: datetime | None) -> datetime | None:
        """
        Rejects a schedule in the past.

        A naive datetime is interpreted as UTC rather than rejected, because clients that
        post an ISO string without an offset are common and silently treating such a value
        as local server time would schedule sends at the wrong hour.
        """
        if v is None:
            return v
        aware = v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)
        if aware <= datetime.now(timezone.utc):
            raise ValueError("scheduled_at must be in the future.")
        return aware


class WhatsAppCampaignCreate(WhatsAppCampaignBase):
    """
    Schema for validating requests to create a campaign.

    `lead_ids` enrols the audience at creation time. It is optional so a campaign can be
    drafted first and populated later via the recipients endpoint.
    `status` is absent: a new campaign is always DRAFT (or SCHEDULED when `scheduled_at`
    is supplied), decided by the service rather than the client.
    """
    template_id: uuid.UUID = Field(..., description="The template whose body this campaign sends")
    lead_ids: List[uuid.UUID] = Field(
        default_factory=list,
        description="Leads to enrol as recipients; may be empty and filled in later",
        max_length=10000,
    )


class WhatsAppCampaignUpdate(BaseModel):
    """
    Schema for validating partial updates to a campaign.
    All fields optional; `version` drives optimistic locking as on Lead.

    Counters and lifecycle status are absent by design: `status` moves only through the
    service's transition methods (start/cancel/schedule), and the `total_*` counters are
    derived from recipient rows, never client-supplied.
    """
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=5000)
    template_id: uuid.UUID | None = Field(None)
    scheduled_at: datetime | None = Field(None)
    version: int | None = Field(None, description="Expected current version, for optimistic locking")

    @field_validator("name")
    @classmethod
    def name_cannot_be_blank(cls, v: str | None) -> str | None:
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            raise ValueError("Campaign name cannot be empty or contain only whitespace.")
        return stripped

    @field_validator("scheduled_at")
    @classmethod
    def scheduled_at_must_be_future(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        aware = v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)
        if aware <= datetime.now(timezone.utc):
            raise ValueError("scheduled_at must be in the future.")
        return aware


class WhatsAppCampaignResponse(BaseModel):
    """
    Schema for serializing a WhatsAppCampaign database record into an API response.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    template_id: uuid.UUID
    name: str
    description: str | None
    status: CampaignStatus
    scheduled_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    total_recipients: int
    total_sent: int
    total_delivered: int
    total_read: int
    total_replied: int
    total_failed: int
    created_by: uuid.UUID | None
    version: int
    created_at: datetime
    updated_at: datetime


class WhatsAppCampaignListResponse(BaseModel):
    """
    Schema for a paginated list of campaigns.
    """
    items: List[WhatsAppCampaignResponse]
    total: int = Field(..., description="Total campaigns matching the filters (ignoring skip/limit)")
    skip: int
    limit: int


class CampaignRecipientAddRequest(BaseModel):
    """
    Schema for enrolling additional leads into an existing campaign.
    """
    lead_ids: List[uuid.UUID] = Field(
        ...,
        description="Leads to enrol as recipients; already-enrolled leads are skipped",
        min_length=1,
        max_length=10000,
    )


class CampaignRecipientResponse(BaseModel):
    """
    Schema for serializing a CampaignRecipient database record into an API response.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID
    lead_id: uuid.UUID
    phone: str
    message_status: MessageStatus
    rendered_message: str | None
    provider_message_id: str | None
    error_message: str | None
    reply_text: str | None
    sent_at: datetime | None
    delivered_at: datetime | None
    read_at: datetime | None
    replied_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CampaignRecipientListResponse(BaseModel):
    """
    Schema for a paginated list of a campaign's recipients.
    """
    items: List[CampaignRecipientResponse]
    total: int = Field(..., description="Total recipients matching the filters (ignoring skip/limit)")
    skip: int
    limit: int


class CampaignStartResponse(BaseModel):
    """
    Schema for the outcome of starting (dispatching) a campaign.

    The campaign is returned alongside the run summary so a client can update its view
    from one response instead of re-fetching.
    """
    campaign: WhatsAppCampaignResponse
    dispatched: int = Field(..., description="Recipients handed to the provider in this run")
    succeeded: int = Field(..., description="Recipients the provider accepted")
    failed: int = Field(..., description="Recipients the provider rejected")
    provider: str = Field(..., description="Name of the provider adapter that handled the run")


class CampaignStatisticsResponse(BaseModel):
    """
    Schema for a campaign's delivery statistics.

    Counts are recomputed from the recipient rows rather than read off the campaign's
    denormalized columns, so this endpoint is authoritative even if a counter has drifted.
    Rates are expressed as percentages of `total_recipients`, rounded to two decimals, and
    are 0.0 for an empty campaign rather than undefined.
    """
    campaign_id: uuid.UUID
    campaign_name: str
    status: CampaignStatus
    total_recipients: int
    pending: int
    queued: int
    sent: int
    delivered: int
    read: int
    failed: int
    replied: int
    delivery_rate: float = Field(..., description="Percentage of recipients that reached DELIVERED or beyond")
    read_rate: float = Field(..., description="Percentage of recipients that reached READ or beyond")
    reply_rate: float = Field(..., description="Percentage of recipients that replied")
    failure_rate: float = Field(..., description="Percentage of recipients whose send failed")
    progress_percent: float = Field(
        ..., description="Percentage of recipients in a terminal-or-dispatched state (campaign completion)"
    )


# =====================================================================
# REPLIES & WEBHOOKS
# =====================================================================

class ReplyWebhookRequest(BaseModel):
    """
    Schema for an inbound reply reported to `/whatsapp/webhook/reply`.

    A reply may be identified either by `provider_message_id` (preferred — it pins the
    reply to the exact outbound message) or by `phone` alone (the fallback several
    providers force on us, resolved against that number's most recent dispatch). At least
    one must be supplied, which is enforced in the model validator below.

    `lead_status` lets an operator override the automatic status mapping; when omitted the
    service derives the new lead status from `reply_type`.
    """
    provider_message_id: str | None = Field(
        None, description="Provider's identifier for the outbound message being replied to", max_length=255
    )
    phone: str | None = Field(
        None, description="Sender's number, used when no provider_message_id is available", max_length=50
    )
    reply_text: str = Field(..., description="Body of the lead's reply", min_length=1, max_length=10000)
    reply_type: str | None = Field(
        None,
        description=(
            "Classified intent of the reply: 'interested', 'not_interested' or "
            "'need_details'. Drives the automatic lead-status update when set."
        ),
        max_length=50,
    )
    lead_status: LeadStatus | None = Field(
        None, description="Explicit lead status to apply, overriding the reply_type mapping"
    )
    replied_at: datetime | None = Field(
        None, description="When the reply was received; defaults to now"
    )

    @field_validator("reply_text")
    @classmethod
    def reply_cannot_be_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Reply text cannot be empty or contain only whitespace.")
        return stripped

    @field_validator("reply_type")
    @classmethod
    def normalize_reply_type(cls, v: str | None) -> str | None:
        """
        Normalizes the classified intent to lowercase with underscores, so 'Not Interested',
        'not-interested' and 'NOT_INTERESTED' all map to the same rule.
        """
        if v is None:
            return v
        return v.strip().lower().replace(" ", "_").replace("-", "_")


class DeliveryStatusWebhookRequest(BaseModel):
    """
    Schema for an inbound delivery-status callback (sent/delivered/read/failed).

    Kept separate from `ReplyWebhookRequest` because a status callback carries no message
    body and must never touch the lead's CRM status, whereas a reply does both.
    """
    provider_message_id: str = Field(
        ..., description="Provider's identifier for the outbound message", max_length=255
    )
    status: MessageStatus = Field(..., description="New delivery state reported by the provider")
    error_message: str | None = Field(
        None, description="Failure reason, when status is FAILED", max_length=5000
    )
    occurred_at: datetime | None = Field(
        None, description="When the event occurred; defaults to now"
    )


class ReplyRecordedResponse(BaseModel):
    """
    Schema for the outcome of recording a reply.

    It reports what the reply actually changed — which recipient row matched, whether the
    lead's CRM status moved, and the activity that was appended — so the caller can verify
    the automation ran without issuing three follow-up reads.
    """
    recipient: CampaignRecipientResponse
    lead_id: uuid.UUID
    lead_status: LeadStatus = Field(..., description="The lead's status after processing the reply")
    lead_status_changed: bool = Field(..., description="Whether the reply moved the lead to a new status")
    activity_id: uuid.UUID | None = Field(
        None, description="The WHATSAPP_REPLIED timeline entry appended for this reply"
    )
