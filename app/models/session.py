"""
app/models/session.py

Defines the SQLAlchemy database model for the UserSession entity.
Under Clean Architecture, this resides in the Enterprise Domain Model layer.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.employee import Employee


class UserSession(Base):
    """
    UserSession database model.
    Tracks active logged-in sessions and refresh tokens (using secure SHA-256 hashes).
    """
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier for the session (UUIDv4)"
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Reference to the associated Employee profile"
    )

    token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
        doc="SHA-256 hash of the opaque refresh token"
    )

    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Timestamp representing when the session was created"
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Timestamp representing when the session/token expires"
    )

    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Timestamp representing when the session/token was last used"
    )

    ip_address: Mapped[str | None] = mapped_column(
        String(45),
        nullable=True,
        doc="Client IP address"
    )

    user_agent: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        doc="Client User-Agent header"
    )

    device_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Client device name derived from user agent or request (optional)"
    )

    is_revoked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Flag indicating if the refresh token/session has been explicitly revoked"
    )

    is_used: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Flag indicating if this refresh token has already been exchanged (RTR check)"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Record creation timestamp"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Record modification timestamp"
    )

    # Relationships
    employee: Mapped["Employee"] = relationship(
        "Employee",
        back_populates="sessions",
        doc="Associated employee profile for this session"
    )
