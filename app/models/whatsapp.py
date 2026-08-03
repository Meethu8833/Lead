"""
app/models/whatsapp.py

This file defines the SQLAlchemy database models for the WhatsApp Campaign Management
module, along with their supporting enums.
Under Clean Architecture, this file belongs to the Enterprise Domain Model layer.

Three entities live here because they are three layers of one feature: bulk outreach.

- `WhatsAppTemplate` is a reusable, provider-agnostic message body with `{{placeholder}}`
  variables. It is the *what* of an outreach campaign.
- `WhatsAppCampaign` is one send of one template to a set of leads, with a lifecycle
  (Draft → Scheduled → Running → Completed / Cancelled) and denormalized counters.
  It is the *when* and *to whom*.
- `CampaignRecipient` is the per-lead delivery record: one row per (campaign, lead), each
  carrying its own message status and the four delivery timestamps. It is the *what
  actually happened*, and it is where provider webhooks land.

Nothing in this module names or imports a WhatsApp provider. Templates store the raw body
rather than a Meta/Twilio template ID, and recipients store an opaque `provider_message_id`
string, so the same schema serves WhatsApp Cloud API, Twilio, Interakt or AiSensy without
a migration. See `app/services/whatsapp_provider.py` for the send-side abstraction.
"""

import enum
import uuid
from datetime import datetime
from sqlalchemy import (
    String,
    Boolean,
    DateTime,
    Text,
    Enum,
    Integer,
    ForeignKey,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.core.database import Base


class TemplateCategory(str, enum.Enum):
    """
    Enum describing the business purpose of a template.

    These mirror the coarse categories every major WhatsApp Business provider requires at
    submission time (marketing vs. utility vs. authentication), so a template created here
    can be mapped onto a provider's own category field when a real integration lands,
    without re-classifying existing rows.
    """
    MARKETING = "MARKETING"
    UTILITY = "UTILITY"
    AUTHENTICATION = "AUTHENTICATION"
    SERVICE = "SERVICE"


class CampaignStatus(str, enum.Enum):
    """
    Enum representing the lifecycle state of a campaign.

    Legal transitions (enforced in `WhatsAppCampaignService`, not by the database):
        DRAFT     -> SCHEDULED | RUNNING | CANCELLED
        SCHEDULED -> RUNNING | CANCELLED | DRAFT
        RUNNING   -> COMPLETED | CANCELLED
        COMPLETED -> (terminal)
        CANCELLED -> (terminal)
    """
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MessageStatus(str, enum.Enum):
    """
    Enum representing the delivery state of one message to one recipient.

    PENDING and QUEUED are deliberately distinct: PENDING means the recipient row exists
    but the campaign has not been started, whereas QUEUED means the campaign has started
    and the message has been handed to the provider abstraction but not yet acknowledged.
    That distinction is what makes a partially-failed campaign start diagnosable.

    REPLIED and FAILED are terminal; SENT -> DELIVERED -> READ is the normal progression
    and is enforced as monotonic by `CampaignRecipientService.apply_status` so an
    out-of-order provider webhook cannot regress a READ message back to SENT.
    """
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    READ = "READ"
    FAILED = "FAILED"
    REPLIED = "REPLIED"


# Monotonic ranking used to reject out-of-order delivery webhooks. A status may only be
# overwritten by one of strictly greater rank. FAILED and REPLIED sit above the delivery
# ladder because both are terminal outcomes that must not be clobbered by a late
# "delivered" callback arriving after the lead has already answered.
MESSAGE_STATUS_RANK: dict[MessageStatus, int] = {
    MessageStatus.PENDING: 0,
    MessageStatus.QUEUED: 1,
    MessageStatus.SENT: 2,
    MessageStatus.DELIVERED: 3,
    MessageStatus.READ: 4,
    MessageStatus.FAILED: 5,
    MessageStatus.REPLIED: 6,
}


class WhatsAppTemplate(Base):
    """
    WhatsAppTemplate database model — a reusable message body with named variables.

    Design Decisions:
    - Primary Key ID: UUIDv4, consistent with every other entity in this system.
    - `message_body` holds the raw text with `{{variable}}` placeholders rather than a
      provider-side template identifier, so the module stays provider-neutral (see the
      module docstring). Rendering happens in the service layer.
    - `variables` is a JSONB array of the placeholder names the body declares. It is
      derived from `message_body` by the service on write rather than trusted from the
      client, so the two can never drift apart.
    - `name` is unique among non-deleted templates (enforced by a partial unique index)
      so operators can refer to a template by name, while a deleted template's name
      becomes reusable.
    - Soft delete + optimistic locking, matching the Lead reference model. A template is
      referenced by historical campaigns, so it must never be hard-deleted out from under
      them.
    """
    __tablename__ = "whatsapp_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier for the template (UUIDv4)"
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        doc="Human-readable template name, unique among non-deleted templates"
    )

    category: Mapped[TemplateCategory] = mapped_column(
        Enum(TemplateCategory, name="whatsapp_template_category"),
        default=TemplateCategory.MARKETING,
        server_default=TemplateCategory.MARKETING.value,
        nullable=False,
        index=True,
        doc="Business purpose of the template (maps onto a provider's category field)"
    )

    language: Mapped[str] = mapped_column(
        String(10),
        default="en",
        server_default="en",
        nullable=False,
        doc="BCP-47-style language code for the message body (e.g. 'en', 'en_US', 'ta')"
    )

    message_body: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Raw message text containing {{variable}} placeholders"
    )

    variables: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        doc="JSON array of placeholder names declared by message_body, derived on write"
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
        index=True,
        doc="Whether the template may be used by new campaigns"
    )

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        doc="Soft delete flag"
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when the template was soft-deleted"
    )

    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
        doc="Optimistic locking version number"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Timestamp when the template was created"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Timestamp when the template was last updated"
    )

    __table_args__ = (
        # Partial unique index: a name is unique only among live templates, so soft-deleting
        # a template frees its name for reuse. A plain UniqueConstraint could not express this.
        Index(
            "uq_whatsapp_templates_name_active",
            "name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
    )

    __mapper_args__ = {
        "version_id_col": version
    }


class WhatsAppCampaign(Base):
    """
    WhatsAppCampaign database model — one send of one template to a set of leads.

    Design Decisions:
    - `template_id` uses ON DELETE RESTRICT rather than CASCADE or SET NULL. A campaign's
      audit value depends on knowing what was actually sent; templates are soft-deleted in
      this system, so RESTRICT only ever blocks a genuine hard delete, which is correct.
    - The five `total_*` columns are denormalized counters maintained by the service layer
      alongside the authoritative `campaign_recipients` rows. They exist so a campaign list
      view can render progress bars without an N+1 aggregate per row; the statistics
      endpoint recomputes from the recipient rows, so a counter drifting is a display bug
      and never a correctness one.
    - `created_by` is a nullable FK to employees.id with ON DELETE SET NULL: campaign
      history must survive the removal of the staff member who launched it.
    - `scheduled_at` is nullable — a Draft campaign has no schedule, and an immediately
      started campaign never needs one.
    - Soft delete + optimistic locking, matching the Lead reference model. The version
      column matters here specifically: two operators hitting "Start" concurrently must
      not both dispatch the same campaign.
    """
    __tablename__ = "whatsapp_campaigns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier for the campaign (UUIDv4)"
    )

    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_templates.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        doc="The template whose body this campaign sends"
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        doc="Human-readable campaign name"
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Free-form description of the campaign's purpose (optional)"
    )

    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        doc="When the campaign is scheduled to run (null for Draft/immediate campaigns)"
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when the campaign actually began dispatching"
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when the campaign finished dispatching"
    )

    status: Mapped[CampaignStatus] = mapped_column(
        Enum(CampaignStatus, name="whatsapp_campaign_status"),
        default=CampaignStatus.DRAFT,
        server_default=CampaignStatus.DRAFT.value,
        nullable=False,
        index=True,
        doc="Current lifecycle state of the campaign"
    )

    total_recipients: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        doc="Denormalized count of recipient rows attached to this campaign"
    )

    total_sent: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        doc="Denormalized count of recipients that reached SENT or beyond"
    )

    total_delivered: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        doc="Denormalized count of recipients that reached DELIVERED or beyond"
    )

    total_read: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        doc="Denormalized count of recipients that reached READ or beyond"
    )

    total_replied: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        doc="Denormalized count of recipients that replied"
    )

    total_failed: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        doc="Denormalized count of recipients whose send failed"
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Employee who created the campaign (null if that employee was removed)"
    )

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        doc="Soft delete flag"
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when the campaign was soft-deleted"
    )

    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
        doc="Optimistic locking version number"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Timestamp when the campaign was created"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Timestamp when the campaign was last updated"
    )

    __mapper_args__ = {
        "version_id_col": version
    }


class CampaignRecipient(Base):
    """
    CampaignRecipient database model — the per-lead delivery record for one campaign.

    Design Decisions:
    - Composite unique constraint on (campaign_id, lead_id): a lead cannot be enrolled in
      the same campaign twice. This is what makes "add recipients" idempotent and is the
      database-level backstop behind the service's de-duplication.
    - `phone` is snapshotted onto this row rather than read through to `Lead.phone` at
      render time. The number a message was actually sent to is a historical fact; if the
      lead later corrects their number, the delivery record must not silently rewrite
      itself.
    - `rendered_message` likewise snapshots the fully-substituted body at dispatch time,
      so editing the template afterwards cannot change what the audit trail says was sent.
    - `provider_message_id` is an opaque provider-assigned string, indexed because inbound
      status webhooks identify a message by it and by nothing else. It is nullable since a
      PENDING recipient has not been dispatched yet.
    - No `version` column: recipient rows are written by webhook callbacks that may arrive
      concurrently and out of order. Optimistic locking would turn a benign race into a
      409; ordering is instead enforced semantically by MESSAGE_STATUS_RANK, which is
      idempotent and commutative under retries. This is a deliberate divergence from the
      Campaign/Template models.
    - Composite index on (campaign_id, message_status) because the hot query for this table
      is "all recipients of one campaign in one state" (progress views and statistics).
    """
    __tablename__ = "campaign_recipients"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier for the recipient row (UUIDv4)"
    )

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="The campaign this recipient belongs to"
    )

    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="The lead being messaged"
    )

    phone: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        doc="Destination number, snapshotted from the lead at enrolment time"
    )

    message_status: Mapped[MessageStatus] = mapped_column(
        Enum(MessageStatus, name="campaign_message_status"),
        default=MessageStatus.PENDING,
        server_default=MessageStatus.PENDING.value,
        nullable=False,
        index=True,
        doc="Current delivery state of this recipient's message"
    )

    rendered_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="The fully-substituted message body as actually dispatched"
    )

    provider_message_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        doc="Opaque provider-assigned message identifier, used to match status webhooks"
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Provider-supplied failure reason when message_status is FAILED"
    )

    reply_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Body of the lead's most recent reply, if any"
    )

    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when the message was accepted by the provider"
    )

    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when the message was delivered to the handset"
    )

    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when the message was read by the recipient"
    )

    replied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp of the lead's most recent reply"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Timestamp when the recipient was enrolled in the campaign"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Timestamp when the recipient row was last updated"
    )

    __table_args__ = (
        UniqueConstraint("campaign_id", "lead_id", name="uq_campaign_recipients_campaign_lead"),
        Index("ix_campaign_recipients_campaign_status", "campaign_id", "message_status"),
    )
