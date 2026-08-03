"""
app/models/photographer.py

This file defines the SQLAlchemy database model for the Photographer entity.
Under Clean Architecture, this file belongs to the Enterprise Domain Model layer.
It represents the persistent structure of the Photographer domain entity in PostgreSQL.
"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Boolean, DateTime, Text, Enum, Integer
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.order import Order



class LeadStatus(str, enum.Enum):
    """
    Enum representing the CRM lifecycle status of a lead/photographer.
    """
    NEW = "NEW"
    CONTACTED = "CONTACTED"
    FOLLOW_UP = "FOLLOW_UP"
    INTERESTED = "INTERESTED"
    NEGOTIATING = "NEGOTIATING"
    CUSTOMER = "CUSTOMER"
    INACTIVE = "INACTIVE"
    REJECTED = "REJECTED"


class LeadPriority(str, enum.Enum):
    """
    Enum representing the priority of a CRM lead.
    """
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ContactMethod(str, enum.Enum):
    """
    Enum representing the last contact method used.
    """
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    WHATSAPP = "WHATSAPP"
    DM = "DM"
    IN_PERSON = "IN_PERSON"
    OTHER = "OTHER"


class Photographer(Base):
    """
    Photographer database model.
    Represents the database structure of a photographer record in PostgreSQL.
    
    Design Decisions:
    - Primary Key ID: UUIDv4 is used instead of Sequential Integers to:
      1. Prevent URL resource enumeration vulnerability (e.g. guessing ID increments).
      2. Keep company scale confidential (sequential keys leak the database size).
      3. Prevent collision issues when scaling to multi-region distributed databases.
    """
    __tablename__ = "photographers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier for the photographer (UUIDv4)"
    )
    
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Full name of the photographer"
    )
    
    studio_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Name of the photography studio"
    )
    
    phone: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        doc="Unique phone number of the photographer"
    )
    
    email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Email address of the photographer (optional)"
    )
    
    city: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="City where the photographer operates"
    )
    
    address: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        doc="Full business address of the photographer (optional)"
    )
    
    category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="Photography category (e.g., Wedding, Portrait, Landscape)"
    )

    # ==========================
    # LEAD FIELDS
    # ==========================
    lead_source: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        doc="Source of the lead (e.g., Google, Instagram, referral, manual)"
    )
    
    lead_status: Mapped[LeadStatus] = mapped_column(
        Enum(LeadStatus, name="leadstatus"),
        default=LeadStatus.NEW,
        server_default=LeadStatus.NEW.value,
        nullable=False,
        doc="Current CRM lead status"
    )
    
    priority: Mapped[LeadPriority | None] = mapped_column(
        Enum(LeadPriority, name="leadpriority"),
        default=LeadPriority.MEDIUM,
        server_default=LeadPriority.MEDIUM.value,
        nullable=True,
        doc="Lead priority status"
    )
    
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        doc="ID of the employee assigned to this lead (optional)"
    )

    # ==========================
    # FOLLOW-UP FIELDS
    # ==========================
    last_contacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp of the last contact with the photographer"
    )
    
    next_followup_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp of when the next follow-up action is due"
    )
    
    last_contact_method: Mapped[ContactMethod | None] = mapped_column(
        Enum(ContactMethod, name="contactmethod"),
        nullable=True,
        doc="Method used during the last contact"
    )
    
    last_contact_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Summary note of the last contact"
    )

    # ==========================
    # MARKETING FIELDS
    # ==========================
    instagram: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Instagram username or profile handle"
    )
    
    facebook: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        doc="Facebook profile URL"
    )
    
    website: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        doc="Website URL of the photographer"
    )

    # ==========================
    # CRM & SYSTEM FIELDS
    # ==========================
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)),
        default=list,
        server_default="{}",
        nullable=False,
        doc="Tags associated with the photographer/lead for classification"
    )
    
    internal_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Internal notes about the photographer/lead"
    )

    customer_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp of when the lead was converted to customer"
    )
    
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        doc="Active status flag of the photographer"
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
        doc="Timestamp when the photographer was soft-deleted"
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
        doc="Timestamp of when the photographer was registered"
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Timestamp of when the photographer record was last updated"
    )

    # SQLAlchemy mapper configuration for optimistic locking
    __mapper_args__ = {
        "version_id_col": version
    }

    # Relationships
    orders: Mapped[list["Order"]] = relationship(
        "Order",
        back_populates="photographer",
        cascade="all, delete-orphan",
        doc="Orders placed by this photographer"
    )


