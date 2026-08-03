"""
app/models/employee.py

Defines the SQLAlchemy database model for the Employee entity.
Under Clean Architecture, this resides in the Enterprise Domain Model layer.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Boolean, DateTime, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.role import Role
    from app.models.session import UserSession


class Employee(Base):
    """
    Employee database model.
    Represents persistent staff profiles, authorization associations, and account security state.
    """
    __tablename__ = "employees"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier for the employee (UUIDv4)"
    )

    employee_code: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        doc="Unique sequential employee code (e.g. EMP-000001)"
    )

    first_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="First name of the employee"
    )

    last_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="Last name of the employee"
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        doc="Unique login email address"
    )

    phone: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        doc="Unique contact phone number"
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Bcrypt hashed password"
    )

    department: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        doc="Assigned department (optional)"
    )

    designation: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        doc="Staff job title/designation (optional)"
    )

    role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="SET NULL"),
        nullable=True,
        doc="Associated security role ID"
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        doc="Active status flag"
    )

    # Security & Lockout Fields
    last_login: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp of the last successful login"
    )

    failed_login_attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Count of consecutive failed login attempts"
    )

    last_failed_login: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp of the last failed login attempt"
    )

    lock_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp until which the account is locked due to security policy"
    )

    # Password Reset Fields
    reset_token: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Active secure password reset token"
    )

    reset_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Expiration timestamp of the password reset token"
    )

    # Profile Fields
    profile_photo_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        doc="URL or local path to employee profile photo"
    )

    # Optimistic Locking
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
        doc="Timestamp when the employee record was created"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Timestamp when the employee record was last updated"
    )

    # Relationships
    role: Mapped["Role | None"] = relationship(
        "Role",
        back_populates="employees",
        doc="Role assigned to this employee"
    )

    sessions: Mapped[list["UserSession"]] = relationship(
        "UserSession",
        back_populates="employee",
        cascade="all, delete-orphan",
        doc="Active sessions/refresh tokens for this employee"
    )

    # SQLAlchemy mapper configuration for optimistic locking
    __mapper_args__ = {
        "version_id_col": version
    }
