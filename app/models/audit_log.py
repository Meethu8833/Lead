"""
app/models/audit_log.py

This file defines the SQLAlchemy database model for the AuditLog entity.
Under Clean Architecture, this resides in the Enterprise Domain Model layer.
"""

import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import String, DateTime, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.core.database import Base


class AuditAction(str, Enum):
    """
    Enum representing the type of operation performed.
    """
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    STATUS_CHANGE = "STATUS_CHANGE"
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILURE = "LOGIN_FAILURE"
    LOGOUT = "LOGOUT"
    PASSWORD_RESET = "PASSWORD_RESET"



class AuditLog(Base):
    """
    AuditLog database model.
    Represents the database structure of system audit trails.
    """
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier for the audit log entry"
    )

    entity_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        doc="Name of the audited model/entity class (e.g. Order, Product)"
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        doc="ID of the audited record"
    )

    action: Mapped[AuditAction] = mapped_column(
        SQLEnum(AuditAction, name="auditaction"),
        nullable=False,
        doc="Type of change performed (CREATE, UPDATE, DELETE, STATUS_CHANGE)"
    )

    performed_by: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="User or system entity that initiated the action"
    )

    old_values: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        doc="Previous database values of changed fields before modification"
    )

    new_values: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        doc="Updated database values after modification"
    )

    ip_address: Mapped[str | None] = mapped_column(
        String(45),
        nullable=True,
        doc="IP address of the client performing the request"
    )

    user_agent: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        doc="Browser user agent string of the client"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Timestamp representing when the audit entry was logged"
    )
