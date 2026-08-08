"""
app/models/lead.py

This file defines the SQLAlchemy database model for the Lead entity and its supporting enums.
Under Clean Architecture, this file belongs to the Enterprise Domain Model layer.
It represents the persistent structure of the Lead domain entity in PostgreSQL.

The Lead entity is the central object of the photographer-acquisition CRM workflow:
raw prospects (scraped, referred, or manually entered) are tracked here before they
convert into a Photographer/customer relationship elsewhere in the system.
"""

import enum
import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Text, Enum, Integer, Float, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.core.database import Base


class LeadStatus(str, enum.Enum):
    """
    Enum representing the CRM lifecycle status of a lead.

    Note on CONVERTED: this member was named CUSTOMER until the Lead Pipeline board was
    built, and was renamed in-place (migration a1f4c7b93e02) so the terminal-success
    status reads the same everywhere the pipeline is spoken about. It is unrelated to
    `app/models/photographer.py`'s own LeadStatus.CUSTOMER, which is a separate enum on a
    separate Postgres type (`leadstatus` vs this one's `lead_status`) and was left alone.
    """
    NEW = "NEW"
    CONTACTED = "CONTACTED"
    MESSAGE_SENT = "MESSAGE_SENT"
    REPLIED = "REPLIED"
    INTERESTED = "INTERESTED"
    FOLLOW_UP = "FOLLOW_UP"
    NEGOTIATION = "NEGOTIATION"
    CONVERTED = "CONVERTED"
    LOST = "LOST"


class LeadSource(str, enum.Enum):
    """
    Enum representing where a lead originated from.
    """
    MANUAL = "MANUAL"
    GOOGLE_MAPS = "GOOGLE_MAPS"
    INSTAGRAM = "INSTAGRAM"
    FACEBOOK = "FACEBOOK"
    JUSTDIAL = "JUSTDIAL"
    REFERRAL = "REFERRAL"
    CSV_IMPORT = "CSV_IMPORT"
    OTHER = "OTHER"


class Lead(Base):
    """
    Lead database model.
    Represents a prospective photographer/studio captured by the acquisition pipeline.

    Design Decisions:
    - Primary Key ID: UUIDv4, consistent with every other entity in this system
      (avoids enumeration and cross-environment collisions).
    - phone: unique + indexed, since it is the primary channel-matching key for
      future WhatsApp/outreach automation (not implemented in this phase).
    - assigned_employee_id: nullable FK to employees.id with ON DELETE SET NULL,
      since a lead must survive the removal of the staff member it was assigned to.
    """
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier for the lead (UUIDv4)"
    )

    business_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        doc="Name of the prospective photography business/studio"
    )

    contact_person: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Name of the primary contact person at the business (optional)"
    )

    phone: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        doc="Unique contact phone number of the lead"
    )

    whatsapp: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        doc="WhatsApp contact number (optional, may differ from phone)"
    )

    email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Contact email address (optional)"
    )

    instagram: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Instagram username or profile handle (optional)"
    )

    facebook: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        doc="Facebook profile/page URL (optional)"
    )

    youtube: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        doc=(
            "YouTube channel/page URL (optional). Collected by the contact extractor from "
            "links published on a business's own website — the platform itself is never "
            "scraped. Sized like `facebook` because both hold a full URL rather than a "
            "handle."
        )
    )

    website: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        doc="Website URL (optional)"
    )

    address: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        doc="Full street address of the lead (optional)"
    )

    city: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        doc="City of operation (optional)"
    )

    district: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        doc="District of operation (optional)"
    )

    state: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        doc="State/province of operation (optional)"
    )

    country: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        doc="Country of operation (optional)"
    )

    latitude: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        doc="Geographic latitude of the lead's location (optional)"
    )

    longitude: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        doc="Geographic longitude of the lead's location (optional)"
    )

    source: Mapped[LeadSource] = mapped_column(
        Enum(LeadSource, name="lead_source"),
        default=LeadSource.MANUAL,
        server_default=LeadSource.MANUAL.value,
        nullable=False,
        index=True,
        doc="Origin channel through which this lead was captured"
    )

    status: Mapped[LeadStatus] = mapped_column(
        Enum(LeadStatus, name="lead_status"),
        default=LeadStatus.NEW,
        server_default=LeadStatus.NEW.value,
        nullable=False,
        index=True,
        doc="Current CRM lifecycle status of the lead"
    )

    assigned_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Employee currently assigned to work this lead (optional)"
    )

    remarks: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Free-form remarks/notes about the lead"
    )

    last_contacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        doc=(
            "Timestamp of the most recent outbound or inbound contact with this lead. "
            "Maintained by the WhatsApp campaign module (on dispatch and on reply); "
            "indexed because 'leads not contacted since X' drives the follow-up worklist."
        )
    )

    is_converted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        doc="Flag indicating whether the lead has converted into a customer"
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
        doc="Timestamp when the lead was soft-deleted"
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
        doc="Timestamp when the lead record was created"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Timestamp when the lead record was last updated"
    )

    # SQLAlchemy mapper configuration for optimistic locking
    __mapper_args__ = {
        "version_id_col": version
    }
